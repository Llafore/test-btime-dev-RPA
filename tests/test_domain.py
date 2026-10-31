"""Testes determinísticos das regras; nenhuma fonte externa é acessada."""

import unittest
from dataclasses import FrozenInstanceError, replace
from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from weather_rpa.domain import DailyForecast, Location, WeatherSource


def location(**changes):
    values = dict(location_id="br-sp-sao-paulo", name="São Paulo", state="SP",
                  latitude=-23.55, longitude=-46.63, timezone="America/Sao_Paulo")
    return Location(**(values | changes))


def forecast(**changes):
    values = dict(location=location(), forecast_date=date(2026, 10, 31),
                  temperature_min_c=15.0, temperature_max_c=27.0,
                  precipitation_mm=2.5, source=WeatherSource.OPEN_METEO,
                  collected_at=datetime(2026, 10, 31, 12, tzinfo=timezone.utc))
    return DailyForecast(**(values | changes))


class LocationTests(unittest.TestCase):
    def test_preserves_internal_reference_and_location_data(self):
        result = location()
        self.assertEqual(result.location_id, "br-sp-sao-paulo")
        self.assertEqual(result.name, "São Paulo")
        self.assertEqual(result.latitude, -23.55)
        self.assertEqual(result.longitude, -46.63)
        self.assertEqual(result.timezone, "America/Sao_Paulo")

    def test_internal_reference_alone_does_not_define_value_equality(self):
        sao_paulo = location()
        other_coordinates = location(latitude=-23.6)
        self.assertNotEqual(sao_paulo, other_coordinates)
        self.assertEqual(sao_paulo, location())

    def test_rejects_missing_or_untrimmed_text(self):
        for field in ("location_id", "name", "state", "timezone"):
            for invalid in (None, "", "  ", " SP", "SP ", 123):
                with self.subTest(field=field, value=invalid):
                    with self.assertRaises(ValueError):
                        location(**{field: invalid})

    def test_rejects_invalid_state_format(self):
        for invalid in ("sp", "S", "SAO", "12", "ÉA"):
            with self.subTest(value=invalid), self.assertRaises(ValueError):
                location(state=invalid)

    def test_accepts_coordinate_boundaries(self):
        for lat, lon in ((-90, -180), (90, 180), (0, 0)):
            with self.subTest(lat=lat, lon=lon):
                self.assertEqual(location(latitude=lat, longitude=lon).latitude, lat)

    def test_rejects_out_of_range_coordinates(self):
        for field, invalid in (("latitude", -90.01), ("latitude", 90.01),
                               ("longitude", -180.01), ("longitude", 180.01)):
            with self.subTest(field=field, value=invalid), self.assertRaises(ValueError):
                location(**{field: invalid})

    def test_rejects_invalid_coordinate_types_and_nonfinite_values(self):
        for field in ("latitude", "longitude"):
            for invalid in (True, False, "1", None, float("nan"), float("inf"), -float("inf")):
                with self.subTest(field=field, value=invalid), self.assertRaises(ValueError):
                    location(**{field: invalid})

    def test_rejects_unknown_and_unsafe_timezone_keys(self):
        for invalid in ("Invalid/City", "/etc/passwd", "../UTC"):
            with self.subTest(value=invalid), self.assertRaises(ValueError):
                location(timezone=invalid)

    def test_is_immutable(self):
        with self.assertRaises(FrozenInstanceError):
            location().name = "Outra cidade"


class DailyForecastTests(unittest.TestCase):
    def test_forecasts_keep_each_location_data_in_a_multiple_city_collection(self):
        sao_paulo = location()
        rio = location(location_id="br-rj-rio", name="Rio de Janeiro", state="RJ",
                       latitude=-22.91, longitude=-43.17)
        results = [forecast(location=sao_paulo), forecast(location=rio)]
        by_location = {result.location.location_id: result for result in results}
        self.assertEqual(len(by_location), 2)
        self.assertEqual(by_location["br-sp-sao-paulo"].location.name, "São Paulo")
        self.assertEqual(by_location["br-rj-rio"].location.name, "Rio de Janeiro")
        self.assertEqual(by_location["br-rj-rio"].location.state, "RJ")
        self.assertEqual(by_location["br-rj-rio"].location.latitude, -22.91)
        self.assertEqual(by_location["br-rj-rio"].location.longitude, -43.17)

    def test_accepts_each_source(self):
        for source in WeatherSource:
            with self.subTest(source=source):
                self.assertIs(forecast(source=source).source, source)

    def test_preserves_missing_zero_and_positive_precipitation(self):
        for value in (None, 0, 0.0, 2.5):
            with self.subTest(value=value):
                self.assertEqual(forecast(precipitation_mm=value).precipitation_mm, value)
        self.assertIsNone(forecast(precipitation_mm=None).precipitation_mm)
        self.assertIsNotNone(forecast(precipitation_mm=0).precipitation_mm)

    def test_rejects_negative_precipitation(self):
        with self.assertRaisesRegex(ValueError, "precipitation_mm"):
            forecast(precipitation_mm=-0.01)

    def test_accepts_negative_and_equal_temperatures(self):
        for low, high in ((-15, -2), (0, 0), (-3, -3)):
            with self.subTest(low=low, high=high):
                result = forecast(temperature_min_c=low, temperature_max_c=high)
                self.assertEqual(result.temperature_min_c, low)
                self.assertEqual(result.temperature_max_c, high)

    def test_rejects_inverted_temperatures(self):
        with self.assertRaisesRegex(ValueError, "temperature_min_c"):
            forecast(temperature_min_c=28, temperature_max_c=27)

    def test_rejects_nonfinite_and_nonnumeric_measurements(self):
        for field in ("temperature_min_c", "temperature_max_c", "precipitation_mm"):
            for invalid in (True, False, "20", float("nan"), float("inf"), -float("inf")):
                with self.subTest(field=field, value=invalid), self.assertRaises(ValueError):
                    forecast(**{field: invalid})

    def test_requires_both_temperatures(self):
        for field in ("temperature_min_c", "temperature_max_c"):
            with self.subTest(field=field), self.assertRaises(ValueError):
                forecast(**{field: None})

    def test_requires_location_object(self):
        for invalid in (None, "São Paulo", {}):
            with self.subTest(value=invalid), self.assertRaises(ValueError):
                forecast(location=invalid)

    def test_requires_date_without_time(self):
        for invalid in (None, "2026-10-31", datetime(2026, 10, 31)):
            with self.subTest(value=invalid), self.assertRaises(ValueError):
                forecast(forecast_date=invalid)

    def test_requires_explicit_source_enum(self):
        for invalid in (None, "unknown", "open_meteo"):
            with self.subTest(value=invalid), self.assertRaises(ValueError):
                forecast(source=invalid)

    def test_requires_aware_collection_datetime(self):
        for invalid in (None, date(2026, 10, 31), "2026-10-31", datetime(2026, 10, 31)):
            with self.subTest(value=invalid), self.assertRaises(ValueError):
                forecast(collected_at=invalid)

    def test_normalizes_collection_to_utc_preserving_instant_and_forecast_day(self):
        collected = datetime(2026, 10, 31, 23, 30, tzinfo=ZoneInfo("America/Sao_Paulo"))
        result = forecast(collected_at=collected)
        self.assertEqual(result.collected_at, datetime(2026, 11, 1, 2, 30, tzinfo=timezone.utc))
        self.assertEqual(result.collected_at.timestamp(), collected.timestamp())
        self.assertEqual(result.collected_at.utcoffset(), timedelta(0))
        self.assertEqual(result.forecast_date, date(2026, 10, 31))
        self.assertEqual(result.location.timezone, "America/Sao_Paulo")

    def test_handles_positive_offset_crossing_previous_utc_day(self):
        collected = datetime(2026, 10, 31, 0, 30, tzinfo=timezone(timedelta(hours=9)))
        result = forecast(collected_at=collected)
        self.assertEqual(result.collected_at, datetime(2026, 10, 30, 15, 30, tzinfo=timezone.utc))
        self.assertEqual(result.forecast_date, date(2026, 10, 31))

    def test_honors_historical_location_offset(self):
        collected = datetime(2018, 12, 1, 12, tzinfo=ZoneInfo("America/Sao_Paulo"))
        result = forecast(collected_at=collected, forecast_date=date(2018, 12, 1))
        self.assertEqual(result.collected_at.hour, 14)

    def test_forecast_day_is_independent_of_collection_day(self):
        result = forecast(forecast_date=date(2020, 1, 1))
        self.assertEqual(result.forecast_date, date(2020, 1, 1))

    def test_is_immutable_and_revalidates_replacement(self):
        result = forecast()
        with self.assertRaises(FrozenInstanceError):
            result.precipitation_mm = -1
        with self.assertRaises(ValueError):
            replace(result, precipitation_mm=-1)


if __name__ == "__main__":
    unittest.main()
