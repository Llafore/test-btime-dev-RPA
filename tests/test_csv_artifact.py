"""Testes com arquivos temporários e entradas locais, sem fontes externas."""

import csv
import unittest
from dataclasses import replace
from datetime import date, datetime, timezone
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from weather_rpa.adapters.csv_artifact import (
    ArtifactValidationError, CsvArtifactValidator, CsvForecastExporter,
    load_forecast_schema,
)
from weather_rpa.domain import DailyForecast, Location, WeatherSource

COLUMNS = [
    "location_name", "state", "latitude", "longitude", "forecast_date", "timezone",
    "temperature_min_c", "temperature_max_c", "precipitation_mm", "source", "collected_at",
]


def make_forecast(**changes):
    values = dict(
        location=Location("internal-sp", "São Paulo", "SP", -23.55, -46.63, "America/Sao_Paulo"),
        forecast_date=date(2026, 10, 31), temperature_min_c=15.25,
        temperature_max_c=27.5, precipitation_mm=2.75, source=WeatherSource.OPEN_METEO,
        collected_at=datetime(2026, 10, 31, 12, 30, tzinfo=timezone.utc),
    )
    return DailyForecast(**(values | changes))


def valid_row(**changes):
    values = dict(zip(COLUMNS, [
        "São Paulo", "SP", "-23.55", "-46.63", "2026-10-31", "America/Sao_Paulo",
        "15.25", "27.5", "2.75", "open_meteo", "2026-10-31T12:30:00+00:00",
    ]))
    return values | changes


class CsvArtifactTests(unittest.TestCase):
    def setUp(self):
        directory = TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.directory = Path(directory.name)
        self.path = self.directory / "forecast.csv"
        self.validator = CsvArtifactValidator()
        self.exporter = CsvForecastExporter()

    def write_rows(self, rows, columns=COLUMNS):
        with self.path.open("w", encoding="utf-8", newline="") as stream:
            writer = csv.DictWriter(stream, fieldnames=columns, lineterminator="\n")
            writer.writeheader()
            writer.writerows(rows)

    def read_rows(self):
        with self.path.open(encoding="utf-8", newline="") as stream:
            reader = csv.DictReader(stream)
            return reader.fieldnames, list(reader)

    def test_export_preserves_data_and_omits_internal_reference(self):
        self.assertEqual(self.exporter.export([make_forecast()], self.path), 1)
        columns, rows = self.read_rows()
        self.assertEqual(columns, COLUMNS)
        self.assertEqual(rows, [valid_row()])
        self.assertNotIn("internal-sp", self.path.read_text(encoding="utf-8"))
        self.assertNotIn("location_id", columns)

    def test_export_preserves_absence_and_zero(self):
        rows = [make_forecast(precipitation_mm=None),
                make_forecast(precipitation_mm=0, forecast_date=date(2026, 11, 1))]
        self.exporter.export(rows, self.path)
        _, values = self.read_rows()
        self.assertEqual(values[0]["precipitation_mm"], "")
        self.assertEqual(values[1]["precipitation_mm"], "0")

    def test_export_supports_multiple_locations_and_sources_from_generator(self):
        first = make_forecast()
        rio = Location("internal-rj", "Rio de Janeiro", "RJ", -22.91, -43.17, "America/Sao_Paulo")
        forecasts = [first, replace(first, location=rio), replace(first, source=WeatherSource.CLIMATEMPO)]
        self.assertEqual(self.exporter.export((f for f in forecasts), self.path), 3)
        _, rows = self.read_rows()
        self.assertEqual([r["location_name"] for r in rows], ["São Paulo", "Rio de Janeiro", "São Paulo"])
        self.assertEqual(rows[1]["latitude"], "-22.91")
        self.assertEqual(rows[2]["source"], "climatempo")

    def test_export_escapes_commas_quotes_and_newlines(self):
        name = 'Cidade, "Centro"\nSul'
        item = make_forecast(location=replace(make_forecast().location, name=name))
        self.exporter.export([item], self.path)
        self.assertEqual(self.read_rows()[1][0]["location_name"], name)
        self.assertEqual(self.validator.validate(self.path), 1)

    def test_export_writes_normalized_utc_and_preserves_forecast_date(self):
        from zoneinfo import ZoneInfo
        item = make_forecast(collected_at=datetime(2026, 10, 31, 23, 30, tzinfo=ZoneInfo("America/Sao_Paulo")))
        self.exporter.export([item], self.path)
        row = self.read_rows()[1][0]
        self.assertEqual(row["collected_at"], "2026-11-01T02:30:00+00:00")
        self.assertEqual(row["forecast_date"], "2026-10-31")
        self.assertEqual(row["timezone"], "America/Sao_Paulo")

    def test_export_replaces_instead_of_appending(self):
        self.path.write_text("previous output", encoding="utf-8")
        self.exporter.export([make_forecast()], self.path)
        self.assertEqual(self.read_rows()[1], [valid_row()])
        self.assertEqual(list(self.directory.iterdir()), [self.path])

    def test_export_rejects_empty_collection_without_publishing(self):
        with self.assertRaises(ArtifactValidationError):
            self.exporter.export([], self.path)
        self.assertEqual(list(self.directory.iterdir()), [])

    def test_export_keeps_existing_file_on_duplicate_validation_failure(self):
        self.path.write_bytes(b"original")
        with self.assertRaisesRegex(ArtifactValidationError, "duplicate"):
            self.exporter.export([make_forecast(), make_forecast()], self.path)
        self.assertEqual(self.path.read_bytes(), b"original")
        self.assertEqual(list(self.directory.iterdir()), [self.path])

    def test_internal_ids_do_not_allow_duplicate_exported_keys(self):
        first = make_forecast()
        second = replace(first, location=replace(first.location, location_id="another-id"))
        with self.assertRaisesRegex(ArtifactValidationError, "duplicate"):
            self.exporter.export([first, second], self.path)
        self.assertFalse(self.path.exists())

    def test_export_keeps_existing_file_if_input_iterator_fails(self):
        def interrupted():
            yield make_forecast()
            raise RuntimeError("interrupted collection")
        self.path.write_bytes(b"original")
        with self.assertRaisesRegex(RuntimeError, "interrupted"):
            self.exporter.export(interrupted(), self.path)
        self.assertEqual(self.path.read_bytes(), b"original")
        self.assertEqual(list(self.directory.iterdir()), [self.path])

    def test_export_rejects_wrong_item_type_and_cleans_temporary_file(self):
        with self.assertRaises(TypeError):
            self.exporter.export([{}], self.path)
        self.assertEqual(list(self.directory.iterdir()), [])

    def test_export_propagates_publication_error_and_cleans_temporary_file(self):
        self.path.write_bytes(b"original")
        with patch.object(Path, "replace", side_effect=PermissionError("destination is locked")):
            with self.assertRaises(PermissionError):
                self.exporter.export([make_forecast()], self.path)
        self.assertEqual(self.path.read_bytes(), b"original")
        self.assertEqual(list(self.directory.iterdir()), [self.path])

    def test_export_requires_existing_parent_directory(self):
        with self.assertRaises(FileNotFoundError):
            self.exporter.export([make_forecast()], self.directory / "missing" / "out.csv")
        self.assertEqual(list(self.directory.iterdir()), [])

    def test_validator_accepts_valid_rows_and_missing_precipitation(self):
        self.write_rows([valid_row(), valid_row(forecast_date="2026-11-01", precipitation_mm="")])
        self.assertEqual(self.validator.validate(self.path), 2)

    def test_validator_rejects_empty_file_and_header_only(self):
        for content in ("", ",".join(COLUMNS) + "\n"):
            with self.subTest(content=content):
                self.path.write_text(content, encoding="utf-8")
                with self.assertRaises(ArtifactValidationError):
                    self.validator.validate(self.path)

    def test_validator_rejects_missing_extra_reordered_and_duplicate_headers(self):
        for columns in (COLUMNS[:-1], COLUMNS + ["location_id"], list(reversed(COLUMNS)),
                        COLUMNS[:-1] + ["source"]):
            with self.subTest(columns=columns):
                self.write_rows([], columns)
                with self.assertRaisesRegex(ArtifactValidationError, "header"):
                    self.validator.validate(self.path)

    def test_validator_requires_all_fields_except_precipitation(self):
        for field in COLUMNS:
            if field == "precipitation_mm":
                continue
            with self.subTest(field=field):
                self.write_rows([valid_row(**{field: ""})])
                with self.assertRaisesRegex(ArtifactValidationError, field):
                    self.validator.validate(self.path)

    def test_validator_rejects_invalid_numbers(self):
        for field in ("latitude", "longitude", "temperature_min_c", "temperature_max_c", "precipitation_mm"):
            for value in ("NaN", "INF", "-inf", "1e999", "True", "12,5", "1_000", " 2", "2 "):
                with self.subTest(field=field, value=value):
                    self.write_rows([valid_row(**{field: value})])
                    with self.assertRaisesRegex(ArtifactValidationError, field):
                        self.validator.validate(self.path)

    def test_validator_rejects_invalid_domain_values(self):
        cases = [dict(latitude="90.1"), dict(longitude="-180.1"),
                 dict(temperature_min_c="28"), dict(precipitation_mm="-0.1"),
                 dict(state="sp"), dict(timezone="Unknown/City"),
                 dict(location_name="   "), dict(source="other")]
        for changes in cases:
            with self.subTest(changes=changes):
                self.write_rows([valid_row(**changes)])
                with self.assertRaises(ArtifactValidationError):
                    self.validator.validate(self.path)

    def test_validator_rejects_invalid_and_noncanonical_dates(self):
        for value in ("2026-02-30", "20261031", "31/10/2026", "2026-10-31T00:00:00"):
            with self.subTest(value=value):
                self.write_rows([valid_row(forecast_date=value)])
                with self.assertRaisesRegex(ArtifactValidationError, "forecast_date"):
                    self.validator.validate(self.path)

    def test_validator_requires_canonical_explicit_utc_timestamp(self):
        for value in ("2026-10-31", "2026-10-31T12:30:00", "2026-10-31T12:30:00-03:00",
                      "2026-10-31T12:30:00Z", "2026-10-31 12:30:00+00:00", "invalid"):
            with self.subTest(value=value):
                self.write_rows([valid_row(collected_at=value)])
                with self.assertRaisesRegex(ArtifactValidationError, "collected_at"):
                    self.validator.validate(self.path)

    def test_validator_detects_duplicates_after_numeric_parsing(self):
        self.write_rows([valid_row(), valid_row(latitude="-23.5500", precipitation_mm="0")])
        with self.assertRaisesRegex(ArtifactValidationError, "line 3: duplicate"):
            self.validator.validate(self.path)

    def test_validator_accepts_negative_temperatures_and_decimal_exponents(self):
        self.write_rows([valid_row(temperature_min_c="-15", temperature_max_c="-2", precipitation_mm="1e-2")])
        self.assertEqual(self.validator.validate(self.path), 1)

    def test_validator_rejects_wrong_row_width_and_blank_rows(self):
        for row in ("a,b", ",".join(["x"] * 12), ""):
            with self.subTest(row=row):
                self.path.write_text(",".join(COLUMNS) + "\n" + row + "\n", encoding="utf-8")
                with self.assertRaises(ArtifactValidationError):
                    self.validator.validate(self.path)

    def test_validator_rejects_malformed_quoting_and_invalid_utf8(self):
        for content in ((",".join(COLUMNS) + '\n"unclosed').encode(), b"\xff\xfe"):
            with self.subTest(content=content):
                self.path.write_bytes(content)
                with self.assertRaises(ArtifactValidationError):
                    self.validator.validate(self.path)

    def test_validator_reports_physical_line_for_broken_csv_after_valid_row(self):
        self.write_rows([valid_row()])
        with self.path.open("a", encoding="utf-8") as stream:
            stream.write('"unclosed')
        with self.assertRaisesRegex(ArtifactValidationError, "line 3:"):
            self.validator.validate(self.path)

    def test_validator_propagates_missing_file_error(self):
        with self.assertRaises(FileNotFoundError):
            self.validator.validate(self.path)

    def test_packaged_contract_defines_expected_columns_and_missing_value(self):
        schema = load_forecast_schema()
        self.assertEqual([f["name"] for f in schema["fields"]], COLUMNS)
        self.assertEqual(schema["missingValues"], [""])
        self.assertNotIn("location_id", schema["primaryKey"])


if __name__ == "__main__":
    unittest.main()
