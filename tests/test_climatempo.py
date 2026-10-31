"""Testes de comportamentos com HTML sintético, sem acesso ao site."""

import csv
import unittest
from dataclasses import replace
from datetime import date, datetime, timezone
from email.message import Message
from io import BytesIO
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import Mock
from urllib.error import HTTPError, URLError

from bs4 import BeautifulSoup

from weather_rpa.adapters.climatempo import ClimatempoCollector, ClimatempoPage
from weather_rpa.adapters.climatempo_http import ClimatempoError, ClimatempoHttpClient
from weather_rpa.adapters.climatempo_parser import ClimatempoSelectors, parse_climatempo_forecasts
from weather_rpa.adapters.csv_artifact import CsvForecastExporter
from weather_rpa.application import CollectWeather, CollectionError
from weather_rpa.domain import Location, WeatherSource

SP = Location("sp", "São Paulo", "SP", -23.55, -46.63, "America/Sao_Paulo")
START, END = date(2026, 12, 31), date(2027, 1, 1)
NOW = datetime(2026, 12, 31, 15, tzinfo=timezone.utc)
PAGE = ClimatempoPage(558, "saopaulo-sp")


def html():
    return (Path(__file__).parent / "fixtures" / "climatempo_daily.html").read_text(encoding="utf-8")


def changed(selector, text=None, remove=False, attribute=None):
    soup = BeautifulSoup(html(), "html.parser")
    node = soup.select_one(selector) if selector == "#mainContent" else soup.select_one("#mainContent").select_one(selector)
    if remove:
        node.decompose()
    elif attribute is not None:
        key, value = attribute
        node[key] = value
    else:
        node.string = text
    return str(soup)


def parse(content):
    return parse_climatempo_forecasts(content, SP, START, END, NOW)


def http_error(code, retry_after=None):
    return HTTPError(PAGE.url, code, "error", {} if retry_after is None else {"Retry-After": retry_after}, BytesIO())


class ClimatempoParserTests(unittest.TestCase):
    def test_reads_scoped_daily_components_and_preserves_zero_and_dates(self):
        rows = parse(html())
        self.assertEqual([r.forecast_date for r in rows], [START, END])
        self.assertEqual(rows[0].temperature_min_c, 16.5)
        self.assertEqual(rows[0].temperature_max_c, 26)
        self.assertEqual(rows[0].precipitation_mm, 12.5)
        self.assertEqual(rows[1].precipitation_mm, 0)
        self.assertEqual(rows[0].location, SP)
        self.assertEqual(rows[0].source, WeatherSource.CLIMATEMPO)
        self.assertEqual(rows[0].collected_at, NOW)

    def test_normalizes_whitespace_case_accents_and_decimal_comma(self):
        content = changed("h1", "Previsão do Tempo para 15 Dias em  SAO   PAULO (sp)")
        self.assertEqual(parse(content)[0].temperature_min_c, 16.5)

    def test_explicit_missing_precipitation_is_none(self):
        for text in ("", "—", "-", "Sem dados", "indisponível"):
            with self.subTest(text=text):
                self.assertIsNone(parse(changed(".agg-daily__rain-text", text))[0].precipitation_mm)

    def test_rejects_missing_or_ambiguous_components(self):
        for selector in ("#mainContent", "h1", "#calendar", ".agg-daily__temp.-min",
                         ".agg-daily__temp.-max", ".agg-daily__rain-text", ".date-inside-circle__day"):
            with self.subTest(selector=selector), self.assertRaises(ClimatempoError):
                parse(changed(selector, remove=True))
        content = html().replace('<span class="agg-daily__rain-text">12,5 mm</span>',
                                 '<span class="agg-daily__rain-text">12mm</span>' * 2)
        with self.assertRaisesRegex(ClimatempoError, "exactly one"):
            parse(content)

    def test_rejects_wrong_city_or_state(self):
        for title in ("Previsão do Tempo para 15 Dias em Rio de Janeiro (RJ)",
                      "Previsão do Tempo para 15 Dias em São Paulo (RJ)", "Changed heading"):
            with self.subTest(title=title), self.assertRaisesRegex(ClimatempoError, "city"):
                parse(changed("h1", title))

    def test_rejects_calendar_misalignment_invalid_dates_and_duplicates(self):
        for value in ('not json', '{}', '[]', '[{"date":"2026-12-31"}]',
                      '[{"date":"2026-12-31"},{"date":"2026-12-31"}]',
                      '[{"date":"2026-12-31"},{"date":"2027-01-02"}]',
                      '[{"date":"2026-02-30"},{"date":"2027-01-01"}]',
                      '[{"date":"20261231"},{"date":"2027-01-01"}]'):
            with self.subTest(value=value), self.assertRaises(ClimatempoError):
                parse(changed("#calendar", attribute=("data-infos", value)))
        with self.assertRaisesRegex(ClimatempoError, "date"):
            parse(changed(".date-inside-circle__day", "30"))

    def test_rejects_invalid_units_probability_and_measurements(self):
        for selector, value in ((".agg-daily__temp.-min", "60°F"),
                                (".agg-daily__temp.-min", ""),
                                (".agg-daily__temp.-min", "30°"),
                                (".agg-daily__rain-text", "95%"),
                                (".agg-daily__rain-text", "-1mm"),
                                (".agg-daily__rain-text", "NaNmm")):
            with self.subTest(value=value), self.assertRaises(ClimatempoError):
                parse(changed(selector, value))

    def test_supports_negative_temperature_with_unicode_minus(self):
        self.assertEqual(parse(changed(".agg-daily__temp.-min", "−2,5 °C"))[0].temperature_min_c, -2.5)

    def test_only_interprets_measurements_inside_requested_period(self):
        content = changed(".agg-daily__rain-text", "malformed future-or-past value")
        rows = parse_climatempo_forecasts(content, SP, END, END, NOW)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0].forecast_date, END)

    def test_rejects_requested_card_unavailable(self):
        with self.assertRaisesRegex(ClimatempoError, "unavailable"):
            parse(changed("section", attribute=("data-weather-state", "error")))

    def test_detects_access_challenges_without_false_positive_from_scripts(self):
        for content in ('<title>Just a moment...</title>', '<form id="challenge-form"></form>',
                        '<div class="g-recaptcha"></div>'):
            with self.subTest(content=content), self.assertRaisesRegex(ClimatempoError, "challenge"):
                parse(content)
        self.assertEqual(len(parse(html() + '<script>var robot = "cloudflare captcha";</script>')), 2)

    def test_selectors_can_change_without_changing_parser(self):
        content = html().replace('agg-daily__temp -min', 'custom-min')
        selectors = replace(ClimatempoSelectors(), temperature_min=".custom-min")
        self.assertEqual(parse_climatempo_forecasts(content, SP, START, END, NOW, selectors)[0].temperature_min_c, 16.5)


class ClimatempoCollectorTests(unittest.TestCase):
    def collector(self, client=None):
        return ClimatempoCollector({"sp": PAGE}, client=client, now=lambda: NOW)

    def test_uses_configured_provider_page_and_filters_period(self):
        client = Mock()
        client.get.return_value = html()
        collector = self.collector(client)
        rows = collector.collect(SP, START, START)
        client.get.assert_called_once_with(PAGE.url)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0].source, WeatherSource.CLIMATEMPO)
        self.assertEqual(rows[0].collected_at, NOW)

    def test_rejects_missing_mapping_and_invalid_requests_without_network(self):
        for location, start, end in ((replace(SP, location_id="unknown"), START, END),
                                    (SP, END, START), (None, START, END),
                                    (SP, NOW, END), (SP, START, "2027-01-01")):
            client = Mock()
            with self.subTest(location=location), self.assertRaises((ValueError, ClimatempoError)):
                self.collector(client).collect(location, start, end)
            client.get.assert_not_called()

    def test_rejects_invalid_page_codes_and_slugs(self):
        for code, slug in ((True, "sp"), (0, "sp"), ("558", "sp"),
                           (558, "../other"), (558, "https://other.test"), (558, "Sao Paulo")):
            with self.subTest(code=code, slug=slug), self.assertRaises(ValueError):
                ClimatempoPage(code, slug)
        with self.assertRaises(ValueError):
            ClimatempoCollector({"sp": PAGE.url})

    def test_propagates_transport_failure(self):
        client = Mock()
        client.get.side_effect = ClimatempoError("blocked")
        with self.assertRaisesRegex(ClimatempoError, "blocked"):
            self.collector(client).collect(SP, START, END)

    def test_missing_dates_are_rejected_by_shared_use_case(self):
        client = Mock()
        client.get.return_value = html()
        exporter = Mock()
        with self.assertRaises(CollectionError):
            CollectWeather(self.collector(client), exporter).execute([SP], START, date(2027, 1, 2), "out.csv")
        exporter.export.assert_not_called()

    def test_local_flow_exports_validated_scraping_csv(self):
        client = Mock()
        client.get.return_value = html()
        with TemporaryDirectory() as directory:
            path = Path(directory) / "weather.csv"
            result = CollectWeather(self.collector(client), CsvForecastExporter()).execute([SP], START, END, path)
            self.assertEqual(result.record_count, 2)
            with path.open(encoding="utf-8", newline="") as stream:
                rows = list(csv.DictReader(stream))
            self.assertEqual(rows[0]["source"], "climatempo")
            self.assertEqual(rows[0]["precipitation_mm"], "12.5")
            self.assertNotIn("location_id", rows[0])


class ClimatempoHttpTests(unittest.TestCase):
    def client(self, responses, **options):
        opener, sleep = Mock(side_effect=responses), Mock()
        return ClimatempoHttpClient(opener=opener, sleep=sleep, now=lambda: NOW, **options), opener, sleep

    def test_get_returns_html_and_sets_timeout(self):
        client, opener, sleep = self.client([BytesIO(html().encode())])
        self.assertEqual(client.get(PAGE.url), html())
        self.assertEqual(opener.call_args.args[0].full_url, PAGE.url)
        self.assertEqual(opener.call_args.kwargs["timeout"], 15)
        sleep.assert_not_called()

    def test_403_and_other_permanent_errors_are_not_retried(self):
        for code in (400, 401, 403, 404):
            client, opener, sleep = self.client([http_error(code)])
            with self.subTest(code=code), self.assertRaisesRegex(ClimatempoError, str(code)):
                client.get(PAGE.url)
            self.assertEqual(opener.call_count, 1)
            sleep.assert_not_called()

    def test_transient_statuses_retry(self):
        for code in (429, 500, 502, 503, 504):
            client, opener, sleep = self.client([http_error(code), BytesIO(b"<html></html>")])
            with self.subTest(code=code):
                self.assertEqual(client.get(PAGE.url), "<html></html>")
                self.assertEqual(opener.call_count, 2)
                sleep.assert_called_once_with(1)

    def test_network_retries_are_bounded_without_final_sleep(self):
        for error in (URLError("offline"), TimeoutError("slow"), ConnectionError("reset")):
            client, opener, sleep = self.client([error] * 3)
            with self.subTest(error=error), self.assertRaises(ClimatempoError):
                client.get(PAGE.url)
            self.assertEqual(opener.call_count, 3)
            self.assertEqual([call.args[0] for call in sleep.call_args_list], [1, 2])

    def test_retry_after_seconds_date_and_invalid_header(self):
        for header, wait in (("7", 7), ("Thu, 31 Dec 2026 15:00:10 GMT", 10), ("invalid", 1)):
            client, _, sleep = self.client([http_error(429, header), BytesIO(b"ok")])
            client.get(PAGE.url)
            sleep.assert_called_once_with(wait)

    def test_retry_after_above_limit_stops_without_early_request(self):
        client, opener, sleep = self.client([http_error(429, "120")])
        with self.assertRaisesRegex(ClimatempoError, "wait limit"):
            client.get(PAGE.url)
        self.assertEqual(opener.call_count, 1)
        sleep.assert_not_called()

    def test_http_limit_has_no_final_sleep(self):
        client, opener, sleep = self.client([http_error(503), http_error(503)], max_attempts=2)
        with self.assertRaises(ClimatempoError):
            client.get(PAGE.url)
        self.assertEqual(opener.call_count, 2)
        sleep.assert_called_once_with(1)

    def test_invalid_encoding_and_content_type_do_not_retry(self):
        response = BytesIO(b"{}")
        response.headers = Message()
        response.headers["Content-Type"] = "application/json"
        for item in (BytesIO(b"\xff"), response):
            client, opener, sleep = self.client([item])
            with self.assertRaises(ClimatempoError):
                client.get(PAGE.url)
            self.assertEqual(opener.call_count, 1)
            sleep.assert_not_called()

    def test_rejects_invalid_configuration(self):
        for options in ({"timeout": 0}, {"timeout": True}, {"max_wait": float("inf")},
                        {"max_attempts": 0}, {"max_attempts": 1.5}, {"max_attempts": 6}):
            with self.subTest(options=options), self.assertRaises(ValueError):
                ClimatempoHttpClient(**options)


if __name__ == "__main__":
    unittest.main()
