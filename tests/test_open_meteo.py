"""Contrato Open-Meteo com respostas controladas e sem rede."""

import csv
import json
import unittest
from datetime import date, datetime, timezone
from io import BytesIO
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import Mock
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qs, urlsplit

from weather_rpa.adapters.open_meteo import OpenMeteoCollector, parse_daily_forecasts
from weather_rpa.adapters.open_meteo_http import OpenMeteoError, OpenMeteoHttpClient
from weather_rpa.adapters.csv_artifact import CsvForecastExporter
from weather_rpa.application import CollectWeather, CollectionError
from weather_rpa.domain import Location, WeatherSource

SP = Location("sp", "São Paulo", "SP", -23.55, -46.63, "America/Sao_Paulo")
START, END = date(2026, 10, 31), date(2026, 11, 1)
NOW = datetime(2026, 10, 31, 15, tzinfo=timezone.utc)


def payload():
    return {
        "latitude": -23.5, "longitude": -46.6,
        "timezone": "America/Sao_Paulo", "utc_offset_seconds": -10800,
        "daily_units": {"time": "iso8601", "temperature_2m_min": "°C",
                        "temperature_2m_max": "°C", "precipitation_sum": "mm"},
        "daily": {"time": ["2026-10-31", "2026-11-01"],
                  "temperature_2m_min": [15, 16], "temperature_2m_max": [25, 27],
                  "precipitation_sum": [None, 0]},
    }


def http_error(status, retry_after=None):
    headers = {} if retry_after is None else {"Retry-After": retry_after}
    return HTTPError("https://api.open-meteo.com", status, "error", headers, BytesIO())


class OpenMeteoParserTests(unittest.TestCase):
    def test_normalizes_daily_values_preserving_location_missing_and_zero(self):
        rows = parse_daily_forecasts(payload(), SP, NOW)
        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[0].forecast_date, START)
        self.assertEqual(rows[1].forecast_date, END)
        self.assertEqual(rows[0].temperature_min_c, 15)
        self.assertEqual(rows[1].temperature_max_c, 27)
        self.assertIsNone(rows[0].precipitation_mm)
        self.assertEqual(rows[1].precipitation_mm, 0)
        self.assertEqual(rows[0].source, WeatherSource.OPEN_METEO)
        self.assertEqual(rows[0].collected_at, NOW)
        self.assertEqual(rows[0].location, SP)
        self.assertEqual(rows[0].location.latitude, -23.55)

    def test_preserves_positive_daily_precipitation(self):
        data = payload()
        data["daily"]["precipitation_sum"][0] = 12.75
        self.assertEqual(parse_daily_forecasts(data, SP, NOW)[0].precipitation_mm, 12.75)

    def test_normalizes_date_and_timezone_whitespace(self):
        data = payload()
        data["timezone"] = " America/Sao_Paulo "
        data["daily"]["time"][0] = " 2026-10-31 "
        self.assertEqual(parse_daily_forecasts(data, SP, NOW)[0].forecast_date, START)

    def test_rejects_missing_or_misaligned_arrays(self):
        for field in ("time", "temperature_2m_min", "temperature_2m_max", "precipitation_sum"):
            for invalid in (None, "invalid"):
                data = payload()
                data["daily"][field] = invalid
                with self.subTest(field=field, invalid=invalid), self.assertRaises(OpenMeteoError):
                    parse_daily_forecasts(data, SP, NOW)
            data = payload()
            del data["daily"][field]
            with self.subTest(missing=field), self.assertRaises(OpenMeteoError):
                parse_daily_forecasts(data, SP, NOW)
        data = payload()
        data["daily"]["temperature_2m_min"] = [15]
        with self.assertRaises(OpenMeteoError):
            parse_daily_forecasts(data, SP, NOW)

    def test_rejects_invalid_units_and_structures(self):
        cases = [None, [], {}, {"error": True}, dict(payload(), daily=[]),
                 dict(payload(), daily_units=None)]
        for key in payload()["daily_units"]:
            data = payload()
            data["daily_units"][key] = "unexpected"
            cases.append(data)
        for data in cases:
            with self.subTest(data=data), self.assertRaises(OpenMeteoError):
                parse_daily_forecasts(data, SP, NOW)

    def test_rejects_invalid_measurements_and_dates(self):
        for field, value in (("temperature_2m_min", None), ("temperature_2m_min", 30),
                             ("temperature_2m_max", float("inf")),
                             ("temperature_2m_min", "15"), ("precipitation_sum", True),
                             ("precipitation_sum", -1), ("precipitation_sum", float("nan")),
                             ("time", "2026-02-30"), ("time", "20261031"), ("time", None)):
            data = payload()
            data["daily"][field][0] = value
            with self.subTest(field=field, value=value), self.assertRaises(OpenMeteoError):
                parse_daily_forecasts(data, SP, NOW)

    def test_rejects_invalid_timezone_or_offset(self):
        for key, value in (("timezone", "Unknown/City"), ("timezone", None),
                           ("utc_offset_seconds", 0), ("utc_offset_seconds", True),
                           ("utc_offset_seconds", "-10800")):
            data = payload()
            data[key] = value
            with self.subTest(key=key, value=value), self.assertRaises(OpenMeteoError):
                parse_daily_forecasts(data, SP, NOW)

    def test_rejects_daily_aggregate_crossing_dst_change(self):
        data = payload()
        data["timezone"] = "America/New_York"
        data["utc_offset_seconds"] = -14400
        ny = Location("ny", "New York", "NY", 40.71, -74.0, "America/New_York")
        with self.assertRaisesRegex(OpenMeteoError, "daily boundaries"):
            parse_daily_forecasts(data, ny, NOW)

    def test_equivalent_timezone_alias_is_accepted(self):
        data = payload()
        data["timezone"] = "GMT"
        data["utc_offset_seconds"] = 0
        location = Location("utc", "UTC sample", "SP", 0, 0, "UTC")
        self.assertEqual(len(parse_daily_forecasts(data, location, NOW)), 2)


class OpenMeteoCollectorTests(unittest.TestCase):
    def test_requests_explicit_location_dates_units_and_local_timezone(self):
        client = Mock()
        client.get.return_value = payload()
        collector = OpenMeteoCollector(client=client, now=lambda: NOW)
        rows = collector.collect(SP, START, END)
        url, params = client.get.call_args.args
        self.assertEqual(url, "https://api.open-meteo.com/v1/forecast")
        self.assertEqual(params, {
            "latitude": -23.55, "longitude": -46.63,
            "daily": "temperature_2m_min,temperature_2m_max,precipitation_sum",
            "timezone": "America/Sao_Paulo", "temperature_unit": "celsius",
            "precipitation_unit": "mm", "timeformat": "iso8601",
            "start_date": "2026-10-31", "end_date": "2026-11-01",
        })
        self.assertEqual(collector.source, WeatherSource.OPEN_METEO)
        self.assertEqual(rows[0].collected_at, rows[1].collected_at)

    def test_rejects_invalid_request_without_http(self):
        for location, start, end in ((None, START, END), (SP, END, START),
                                     (SP, NOW, END), (SP, START, "2026-11-01")):
            client = Mock()
            with self.subTest(start=start), self.assertRaises(ValueError):
                OpenMeteoCollector(client=client).collect(location, start, end)
            client.get.assert_not_called()

    def test_propagates_client_failure(self):
        client = Mock()
        client.get.side_effect = OpenMeteoError("unavailable")
        with self.assertRaisesRegex(OpenMeteoError, "unavailable"):
            OpenMeteoCollector(client=client).collect(SP, START, END)

    def test_shared_use_case_detects_incomplete_response(self):
        client = Mock()
        client.get.return_value = payload()
        for values in client.get.return_value["daily"].values():
            values.pop()
        exporter = Mock()
        with self.assertRaises(CollectionError):
            CollectWeather(OpenMeteoCollector(client=client), exporter).execute([SP], START, END, "out.csv")
        exporter.export.assert_not_called()

    def test_local_flow_from_simulated_api_to_validated_csv(self):
        client = Mock()
        client.get.return_value = payload()
        collector = OpenMeteoCollector(client=client, now=lambda: NOW)
        with TemporaryDirectory() as directory:
            path = Path(directory) / "weather.csv"
            result = CollectWeather(collector, CsvForecastExporter()).execute([SP], START, END, path)
            self.assertEqual(result.record_count, 2)
            with path.open(encoding="utf-8", newline="") as stream:
                rows = list(csv.DictReader(stream))
            self.assertEqual(rows[0]["source"], "open_meteo")
            self.assertEqual(rows[0]["precipitation_mm"], "")
            self.assertEqual(rows[1]["precipitation_mm"], "0")


class OpenMeteoHttpTests(unittest.TestCase):
    def client(self, responses, **options):
        opener = Mock(side_effect=responses)
        sleep = Mock()
        return OpenMeteoHttpClient(opener=opener, sleep=sleep, now=lambda: NOW, **options), opener, sleep

    def test_encodes_query_and_sets_timeout(self):
        client, opener, sleep = self.client([BytesIO(json.dumps(payload()).encode())])
        self.assertEqual(client.get("https://api.open-meteo.com/v1/forecast", {"timezone": SP.timezone}), payload())
        request = opener.call_args.args[0]
        self.assertEqual(parse_qs(urlsplit(request.full_url).query), {"timezone": [SP.timezone]})
        self.assertEqual(opener.call_args.kwargs["timeout"], 15)
        sleep.assert_not_called()

    def test_retries_transient_http_errors_then_succeeds(self):
        for status in (429, 500, 502, 503, 504):
            with self.subTest(status=status):
                client, opener, sleep = self.client([http_error(status), BytesIO(b"{}")])
                self.assertEqual(client.get("https://example.test", {}), {})
                self.assertEqual(opener.call_count, 2)
                sleep.assert_called_once_with(1)

    def test_exhausts_network_retries_without_sleep_after_last_attempt(self):
        for error in (URLError("offline"), TimeoutError("timeout"), ConnectionError("reset")):
            with self.subTest(error=error):
                client, opener, sleep = self.client([error, error, error])
                with self.assertRaises(OpenMeteoError):
                    client.get("https://example.test", {})
                self.assertEqual(opener.call_count, 3)
                self.assertEqual([c.args[0] for c in sleep.call_args_list], [1, 2])

    def test_retries_interrupted_response_body(self):
        from http.client import IncompleteRead
        class InterruptedResponse(BytesIO):
            def read(self):
                raise IncompleteRead(b"partial", 10)
        client, opener, sleep = self.client([InterruptedResponse(), BytesIO(b"{}")])
        self.assertEqual(client.get("https://example.test", {}), {})
        self.assertEqual(opener.call_count, 2)
        sleep.assert_called_once_with(1)

    def test_does_not_retry_permanent_http_errors(self):
        for status in (400, 401, 403, 404):
            client, opener, sleep = self.client([http_error(status)])
            with self.subTest(status=status), self.assertRaisesRegex(OpenMeteoError, str(status)):
                client.get("https://example.test", {})
            self.assertEqual(opener.call_count, 1)
            sleep.assert_not_called()

    def test_honors_retry_after_seconds_and_http_date(self):
        for header, expected in (("7", 7), ("Sat, 31 Oct 2026 15:00:10 GMT", 10), ("invalid", 1)):
            client, _, sleep = self.client([http_error(429, header), BytesIO(b"{}")])
            client.get("https://example.test", {})
            sleep.assert_called_once_with(expected)

    def test_aborts_if_retry_after_exceeds_wait_budget(self):
        client, opener, sleep = self.client([http_error(429, "120")])
        with self.assertRaisesRegex(OpenMeteoError, "wait limit"):
            client.get("https://example.test", {})
        self.assertEqual(opener.call_count, 1)
        sleep.assert_not_called()

    def test_http_retry_limit_does_not_sleep_after_final_error(self):
        client, opener, sleep = self.client([http_error(503), http_error(503)], max_attempts=2)
        with self.assertRaises(OpenMeteoError):
            client.get("https://example.test", {})
        self.assertEqual(opener.call_count, 2)
        sleep.assert_called_once_with(1)

    def test_rejects_invalid_json_nonobject_and_api_errors_without_retry(self):
        for data in (b"not-json", b"[]", b"null", b'{"error":true}', b"\xff"):
            client, opener, sleep = self.client([BytesIO(data)])
            with self.subTest(data=data), self.assertRaises(OpenMeteoError):
                client.get("https://example.test", {})
            self.assertEqual(opener.call_count, 1)
            sleep.assert_not_called()

    def test_rejects_invalid_retry_configuration(self):
        for options in ({"timeout": 0}, {"timeout": True}, {"max_wait": float("inf")},
                        {"max_attempts": 0}, {"max_attempts": 6}, {"max_attempts": 1.5}):
            with self.subTest(options=options), self.assertRaises(ValueError):
                OpenMeteoHttpClient(**options)


if __name__ == "__main__":
    unittest.main()
