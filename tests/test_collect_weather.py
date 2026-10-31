"""Comportamentos do caso de uso com dependências locais substituíveis."""

import csv
import unittest
from dataclasses import replace
from datetime import date, datetime, timezone
from pathlib import Path
from tempfile import TemporaryDirectory

from weather_rpa.application import CollectWeather, CollectionError
from weather_rpa.adapters.csv_artifact import ArtifactValidationError, CsvForecastExporter
from weather_rpa.domain import DailyForecast, Location, WeatherSource

START = date(2026, 10, 31)
END = date(2026, 11, 1)
SP = Location("sp", "São Paulo", "SP", -23.55, -46.63, "America/Sao_Paulo")
RJ = Location("rj", "Rio de Janeiro", "RJ", -22.91, -43.17, "America/Sao_Paulo")


def forecast(location=SP, day=START, source=WeatherSource.OPEN_METEO):
    return DailyForecast(location, day, 15, 27, None, source,
                         datetime(2026, 10, 31, 12, tzinfo=timezone.utc))


class FakeCollector:
    def __init__(self, rows=None, source=WeatherSource.OPEN_METEO):
        self.source = source
        self.rows = rows if rows is not None else {"sp": [forecast(), forecast(day=END)]}
        self.calls = []

    def collect(self, location, start_date, end_date):
        self.calls.append((location, start_date, end_date))
        rows = self.rows[location.location_id]
        if isinstance(rows, Exception):
            raise rows
        return iter(rows)


class FakeExporter:
    def __init__(self, error=None):
        self.calls = []
        self.error = error

    def export(self, forecasts, destination):
        rows = list(forecasts)
        self.calls.append((rows, destination))
        if self.error is not None:
            raise self.error
        return len(rows)


class CollectWeatherTests(unittest.TestCase):
    def test_exports_complete_collection_and_returns_result(self):
        collector, exporter = FakeCollector(), FakeExporter()
        result = CollectWeather(collector, exporter).execute([SP], START, END, "out.csv")
        self.assertEqual(collector.calls, [(SP, START, END)])
        self.assertEqual(exporter.calls, [([forecast(), forecast(day=END)], Path("out.csv"))])
        self.assertEqual(result.destination, Path("out.csv"))
        self.assertEqual(result.record_count, 2)
        self.assertEqual(result.location_count, 1)

    def test_handles_both_sources_using_the_same_use_case(self):
        for source in WeatherSource:
            with self.subTest(source=source):
                collector = FakeCollector({"sp": [forecast(source=source)]}, source)
                exporter = FakeExporter()
                result = CollectWeather(collector, exporter).execute([SP], START, START, "out.csv")
                self.assertEqual(result.record_count, 1)
                self.assertEqual(exporter.calls[0][0][0].source, source)

    def test_collects_multiple_locations_before_one_export_and_sorts_days(self):
        collector = FakeCollector({"sp": [forecast(day=END), forecast()],
                                   "rj": [forecast(RJ, END), forecast(RJ)]})
        exporter = FakeExporter()
        result = CollectWeather(collector, exporter).execute((p for p in (SP, RJ)), START, END, "out.csv")
        self.assertEqual(result.record_count, 4)
        self.assertEqual(result.location_count, 2)
        self.assertEqual(collector.calls, [(SP, START, END), (RJ, START, END)])
        self.assertEqual(len(exporter.calls), 1)
        self.assertEqual(exporter.calls[0][0], [forecast(), forecast(day=END), forecast(RJ), forecast(RJ, END)])

    def test_rejects_invalid_requests_before_any_external_operation(self):
        cases = [([], START, END), ([None], START, END), ([SP], END, START),
                 ([SP], "2026-10-31", END), ([SP], START, None),
                 ([SP], datetime(2026, 10, 31), END),
                 ([SP], START, datetime(2026, 11, 1)),
                 ([SP, SP], START, END),
                 ([SP, replace(SP, name="Outra cidade")], START, END),
                 ([SP, replace(SP, location_id="another")], START, END)]
        for locations, start, end in cases:
            with self.subTest(locations=locations, start=start, end=end):
                collector, exporter = FakeCollector(), FakeExporter()
                with self.assertRaises(ValueError):
                    CollectWeather(collector, exporter).execute(locations, start, end, "out.csv")
                self.assertEqual(collector.calls, [])
                self.assertEqual(exporter.calls, [])

    def test_rejects_invalid_collector_source_before_collection(self):
        collector, exporter = FakeCollector(source="open_meteo"), FakeExporter()
        with self.assertRaises(ValueError):
            CollectWeather(collector, exporter).execute([SP], START, END, "out.csv")
        self.assertEqual(collector.calls, [])
        self.assertEqual(exporter.calls, [])

    def test_rejects_incomplete_duplicate_out_of_range_and_unexpected_records(self):
        cases = [[], [forecast()], [forecast(), forecast()],
                 [forecast(day=date(2026, 10, 30)), forecast(day=END)],
                 [forecast(), forecast(day=date(2026, 11, 2))],
                 [forecast(RJ), forecast(RJ, END)],
                 [forecast(source=WeatherSource.CLIMATEMPO), forecast(day=END)],
                 [forecast(), {}]]
        for rows in cases:
            with self.subTest(rows=rows):
                exporter = FakeExporter()
                with self.assertRaises(CollectionError):
                    CollectWeather(FakeCollector({"sp": rows}), exporter).execute([SP], START, END, "out.csv")
                self.assertEqual(exporter.calls, [])

    def test_second_location_failure_prevents_export_of_first_location(self):
        for rows in ([], OSError("source unavailable")):
            with self.subTest(rows=rows):
                exporter = FakeExporter()
                collector = FakeCollector({"sp": [forecast(), forecast(day=END)], "rj": rows})
                with self.assertRaises((CollectionError, OSError)):
                    CollectWeather(collector, exporter).execute([SP, RJ], START, END, "out.csv")
                self.assertEqual(exporter.calls, [])

    def test_lazy_collection_failure_prevents_export(self):
        def interrupted():
            yield forecast()
            raise TimeoutError("source timeout")
        exporter = FakeExporter()
        with self.assertRaisesRegex(TimeoutError, "source timeout"):
            CollectWeather(FakeCollector({"sp": interrupted()}), exporter).execute([SP], START, END, "out.csv")
        self.assertEqual(exporter.calls, [])

    def test_request_generator_failure_prevents_all_collection(self):
        def interrupted():
            yield SP
            raise RuntimeError("invalid input stream")
        collector, exporter = FakeCollector(), FakeExporter()
        with self.assertRaises(RuntimeError):
            CollectWeather(collector, exporter).execute(interrupted(), START, END, "out.csv")
        self.assertEqual(collector.calls, [])
        self.assertEqual(exporter.calls, [])

    def test_propagates_export_error_without_returning_success(self):
        error = PermissionError("destination locked")
        with self.assertRaises(PermissionError) as raised:
            CollectWeather(FakeCollector(), FakeExporter(error)).execute([SP], START, END, "out.csv")
        self.assertIs(raised.exception, error)

    def test_handles_year_boundary_and_leap_day(self):
        for start, end in ((date(2026, 12, 31), date(2027, 1, 1)),
                           (date(2024, 2, 28), date(2024, 3, 1))):
            from datetime import timedelta
            days = [start + timedelta(days=i) for i in range((end - start).days + 1)]
            collector = FakeCollector({"sp": [forecast(day=day) for day in days]})
            with self.subTest(start=start, end=end):
                result = CollectWeather(collector, FakeExporter()).execute([SP], start, end, "out.csv")
                self.assertEqual(result.record_count, len(days))

    def test_use_case_with_real_csv_exporter(self):
        with TemporaryDirectory() as directory:
            destination = Path(directory) / "out.csv"
            result = CollectWeather(FakeCollector(), CsvForecastExporter()).execute([SP], START, END, destination)
            self.assertEqual(result.record_count, 2)
            with destination.open(encoding="utf-8", newline="") as stream:
                rows = list(csv.DictReader(stream))
            self.assertEqual([row["forecast_date"] for row in rows], ["2026-10-31", "2026-11-01"])
            self.assertEqual(rows[0]["location_name"], "São Paulo")
            self.assertEqual(rows[0]["precipitation_mm"], "")
            self.assertNotIn("location_id", rows[0])

    def test_injected_validator_checks_temporary_before_publication(self):
        class RejectingValidator:
            def validate(self, path):
                self.checked = Path(path).read_text(encoding="utf-8")
                raise ArtifactValidationError("rejected by injected validator")
        validator = RejectingValidator()
        with TemporaryDirectory() as directory:
            destination = Path(directory) / "out.csv"
            destination.write_bytes(b"previous output")
            exporter = CsvForecastExporter(validator=validator)
            with self.assertRaisesRegex(ArtifactValidationError, "injected validator"):
                CollectWeather(FakeCollector(), exporter).execute([SP], START, END, destination)
            self.assertIn("location_name", validator.checked)
            self.assertEqual(destination.read_bytes(), b"previous output")
            self.assertEqual(list(Path(directory).iterdir()), [destination])


if __name__ == "__main__":
    unittest.main()
