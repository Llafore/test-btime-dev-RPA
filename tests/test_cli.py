"""Configuração e interfaces de execução, sem consultas online."""

import io
import json
import unittest
from contextlib import redirect_stderr, redirect_stdout
from datetime import date, datetime, timezone
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from weather_rpa.application import CollectionResult
from weather_rpa.configuration import LocationCatalog, load_locations
from weather_rpa.cli import main
from weather_rpa.domain import Location
from weather_rpa.handlers import api, scraping

START = date(2026, 12, 31)
NOW = datetime(2026, 12, 31, 15, tzinfo=timezone.utc)
SP = Location("sp", "São Paulo", "SP", -23.55, -46.63, "America/Sao_Paulo")


def config():
    return {"locations": [{"location_id": "sp", "name": "São Paulo", "state": "SP",
                           "latitude": -23.55, "longitude": -46.63,
                           "timezone": "America/Sao_Paulo",
                           "climatempo": {"city_code": 558, "slug": "saopaulo-sp"}}]}


class ConfigurationTests(unittest.TestCase):
    def load(self, data):
        with TemporaryDirectory() as directory:
            path = Path(directory) / "locations.json"
            path.write_text(json.dumps(data), encoding="utf-8")
            return load_locations(path)

    def test_packaged_default_catalog(self):
        catalog = load_locations()
        self.assertEqual(catalog.locations, (SP,))
        self.assertEqual(catalog.pages["sp"].city_code, 558)

    def test_normalizes_input_before_domain_validation(self):
        data = config()
        data["locations"][0].update(location_id=" sp ", name=" São Paulo ", state=" sp ",
                                    timezone=" America/Sao_Paulo ")
        self.assertEqual(self.load(data).locations, (SP,))

    def test_provider_page_is_optional_for_api(self):
        data = config()
        del data["locations"][0]["climatempo"]
        self.assertEqual(self.load(data).pages, {})

    def test_rejects_bad_shape_missing_unknown_and_invalid_values(self):
        cases = [None, [], {}, {"locations": []}, {"locations": {}}, {"locations": [None]},
                 {"locations": [dict(config()["locations"][0], typo=True)]},
                 {"locations": [{}]}, {"locations": config()["locations"], "extra": True}]
        for field, value in (("latitude", 100), ("state", ""), ("timezone", "unknown"),
                             ("climatempo", {}), ("climatempo", {"city_code": 0, "slug": "sp"})):
            data = config()
            data["locations"][0][field] = value
            cases.append(data)
        for data in cases:
            with self.subTest(data=data), self.assertRaises(ValueError):
                self.load(data)

    def test_rejects_duplicate_ids_and_duplicate_location_values(self):
        for changes in ({}, {"name": "Outra cidade"}, {"location_id": "sp2"}):
            data = config()
            data["locations"].append(data["locations"][0] | changes)
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                self.load(data)

    def test_accepts_multiple_distinct_locations(self):
        data = config()
        data["locations"].append(dict(data["locations"][0], location_id="rj", name="Rio de Janeiro",
                                      state="RJ", latitude=-22.91, longitude=-43.17))
        self.assertEqual(len(self.load(data).locations), 2)

    def test_missing_file_and_invalid_json_are_errors(self):
        with TemporaryDirectory() as directory:
            path = Path(directory) / "missing.json"
            with self.assertRaises(FileNotFoundError):
                load_locations(path)
            path.write_text("not-json", encoding="utf-8")
            with self.assertRaises(ValueError):
                load_locations(path)


class CliTests(unittest.TestCase):
    def setUp(self):
        self.directory = TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.path = Path(self.directory.name) / "nested" / "out.csv"
        self.catalog = load_locations()
        self.result = CollectionResult(self.path, 1, 1)
        for name in ("logging.basicConfig", "logger"):
            patcher = patch("weather_rpa.cli." + name)
            patcher.start()
            self.addCleanup(patcher.stop)

    def invoke(self, arguments, **kwargs):
        self.stdout, self.stderr = io.StringIO(), io.StringIO()
        with redirect_stdout(self.stdout), redirect_stderr(self.stderr):
            return main(arguments, **kwargs)

    def args(self, mode="--api"):
        return [mode, "--start-date", "2026-12-31", "--output", str(self.path)]

    def test_dispatches_api_with_explicit_options_and_creates_parent(self):
        with patch("weather_rpa.cli.handle_api", return_value=self.result) as api_handler, \
             patch("weather_rpa.cli.handle_scraping") as scraping_handler:
            code = self.invoke(self.args() + ["--timeout", "4", "--attempts", "2"])
        self.assertEqual(code, 0)
        api_handler.assert_called_once_with((SP,), START, START, self.path, timeout=4.0, attempts=2)
        scraping_handler.assert_not_called()
        self.assertTrue(self.path.parent.is_dir())
        self.assertIn("1 registros", self.stdout.getvalue())

    def test_dispatches_scraping_with_provider_mapping(self):
        with patch("weather_rpa.cli.handle_scraping", return_value=self.result) as handler:
            self.assertEqual(self.invoke(self.args("--scraping")), 0)
        self.assertEqual(handler.call_args.kwargs["pages"], self.catalog.pages)

    def test_standalone_mode_does_not_require_mode_flag(self):
        with patch("weather_rpa.cli.handle_api", return_value=self.result) as handler:
            self.assertEqual(self.invoke(self.args()[1:], mode="api"), 0)
        handler.assert_called_once()

    def test_argument_errors_have_exit_code_two(self):
        cases = [[], ["--api", "--scraping"], ["--http"],
                 ["--api", "--start-date", "20261231"],
                 ["--api", "--end-date", "2026-12-31"],
                 ["--api", "--start-date", "2027-01-01", "--end-date", "2026-12-31"],
                 ["--api", "--timeout", "nan"], ["--api", "--timeout", "0"],
                 ["--api", "--attempts", "0"]]
        with patch("weather_rpa.cli.handle_api") as handler:
            for args in cases:
                with self.subTest(args=args), self.assertRaises(SystemExit) as raised:
                    self.invoke(args)
                self.assertEqual(raised.exception.code, 2)
        handler.assert_not_called()

    def test_unknown_duplicate_locations_and_missing_scraping_mapping_fail_before_handler(self):
        for args in (self.args() + ["--location", "unknown"],
                     self.args() + ["--location", "sp", "--location", "sp"]):
            with patch("weather_rpa.cli.handle_api") as handler:
                self.assertEqual(self.invoke(args), 1)
                handler.assert_not_called()
        catalog = LocationCatalog((SP,), {})
        with patch("weather_rpa.cli.load_locations", return_value=catalog), \
             patch("weather_rpa.cli.handle_scraping") as handler:
            self.assertEqual(self.invoke(self.args("--scraping")), 1)
            handler.assert_not_called()
        self.assertFalse(self.path.parent.exists())

    def test_preserves_requested_location_order_and_date_range(self):
        rio = Location("rj", "Rio de Janeiro", "RJ", -22.91, -43.17, SP.timezone)
        catalog = LocationCatalog((SP, rio), {})
        with patch("weather_rpa.cli.load_locations", return_value=catalog), \
             patch("weather_rpa.cli.handle_api", return_value=self.result) as handler:
            self.assertEqual(self.invoke(self.args() + ["--end-date", "2027-01-01",
                "--location", "rj", "--location", "sp"]), 0)
        self.assertEqual(handler.call_args.args[:3], ((rio, SP), START, date(2027, 1, 1)))

    def test_default_date_is_today_in_local_timezone(self):
        with patch("weather_rpa.cli.datetime") as clock, \
             patch("weather_rpa.cli.handle_api", return_value=self.result) as handler:
            clock.now.return_value = NOW
            self.assertEqual(self.invoke(["--api", "--output", str(self.path)]), 0)
        self.assertEqual(handler.call_args.args[1:3], (START, START))
        self.assertEqual(clock.now.call_args.args[0].key, SP.timezone)

    def test_default_dates_must_agree_for_multiple_timezones(self):
        other = Location("other", "Other", "SP", 0, 0, "UTC")
        with patch("weather_rpa.cli.load_locations", return_value=LocationCatalog((SP, other), {})), \
             patch("weather_rpa.cli.datetime") as clock, patch("weather_rpa.cli.handle_api") as handler:
            clock.now.side_effect = [NOW, datetime(2027, 1, 1, tzinfo=timezone.utc)]
            self.assertEqual(self.invoke(["--api", "--output", str(self.path)]), 1)
            handler.assert_not_called()

    def test_config_and_runtime_errors_return_one_without_success_message(self):
        for error in (ValueError("invalid config"), FileNotFoundError("missing config")):
            with patch("weather_rpa.cli.load_locations", side_effect=error):
                self.assertEqual(self.invoke(self.args()), 1)
                self.assertEqual(self.stdout.getvalue(), "")
        from weather_rpa.adapters.open_meteo_http import OpenMeteoError
        for error in (PermissionError("locked"), OpenMeteoError("offline")):
            with patch("weather_rpa.cli.handle_api", side_effect=error):
                self.assertEqual(self.invoke(self.args()), 1)
                self.assertEqual(self.stdout.getvalue(), "")

    def test_keyboard_interrupt_returns_130(self):
        with patch("weather_rpa.cli.handle_api", side_effect=KeyboardInterrupt):
            self.assertEqual(self.invoke(self.args()), 130)

    def test_default_destination_is_separate_for_each_source(self):
        for mode, handler_name, expected in (("--api", "handle_api", "open_meteo.csv"),
                                              ("--scraping", "handle_scraping", "climatempo.csv")):
            with self.subTest(mode=mode), patch("weather_rpa.cli." + handler_name, return_value=self.result) as handler, \
                 patch("weather_rpa.cli.Path.mkdir"):
                self.assertEqual(self.invoke([mode, "--start-date", "2026-12-31"]), 0)
            self.assertEqual(handler.call_args.args[3], Path("output") / expected)

    def test_config_path_is_forwarded(self):
        with patch("weather_rpa.cli.load_locations", return_value=self.catalog) as loader, \
             patch("weather_rpa.cli.handle_api", return_value=self.result):
            self.assertEqual(self.invoke(self.args() + ["--config", "custom.json"]), 0)
        loader.assert_called_once_with(Path("custom.json"))

    def test_cli_scraping_flow_with_local_html(self):
        content = (Path(__file__).parent / "fixtures" / "climatempo_daily.html").read_text(encoding="utf-8")
        with patch("weather_rpa.adapters.climatempo_http.ClimatempoHttpClient.get", return_value=content):
            self.assertEqual(self.invoke(self.args("--scraping")), 0)
        self.assertTrue(self.path.exists())


class HandlerTests(unittest.TestCase):
    def test_api_composes_transport_collector_and_shared_use_case(self):
        with patch.object(api, "OpenMeteoHttpClient") as client, \
             patch.object(api, "OpenMeteoCollector") as collector, \
             patch.object(api, "CollectWeather") as use_case:
            result = api.handle((SP,), START, START, Path("out.csv"), timeout=4, attempts=2)
        client.assert_called_once_with(timeout=4, max_attempts=2)
        collector.assert_called_once_with(client=client.return_value)
        use_case.return_value.execute.assert_called_once_with((SP,), START, START, Path("out.csv"))
        self.assertIs(result, use_case.return_value.execute.return_value)

    def test_scraping_composes_page_mapping(self):
        pages = load_locations().pages
        with patch.object(scraping, "ClimatempoHttpClient") as client, \
             patch.object(scraping, "ClimatempoCollector") as collector, \
             patch.object(scraping, "CollectWeather") as use_case:
            scraping.handle((SP,), START, START, Path("out.csv"), pages=pages)
        collector.assert_called_once_with(pages, client=client.return_value)
        use_case.return_value.execute.assert_called_once_with((SP,), START, START, Path("out.csv"))


if __name__ == "__main__":
    unittest.main()
