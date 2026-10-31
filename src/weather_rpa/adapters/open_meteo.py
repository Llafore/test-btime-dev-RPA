"""Coletor Open-Meteo: consulta diária e normalização para o domínio."""

from datetime import date, datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from weather_rpa.domain import DailyForecast, Location, WeatherSource
from .open_meteo_http import OpenMeteoError, OpenMeteoHttpClient

DAILY_FIELDS = ("temperature_2m_min", "temperature_2m_max", "precipitation_sum")


def parse_daily_forecasts(payload: dict, location: Location, collected_at: datetime) -> list[DailyForecast]:
    """Interpreta uma resposta local, sem HTTP, relógio ou escrita em arquivos.

    A API retorna coordenadas da célula do modelo: preservamos as coordenadas da
    localidade solicitada. Cobertura e datas duplicadas pertencem ao caso de uso.
    """
    try:
        if not isinstance(payload, dict) or payload.get("error"):
            raise ValueError("expected a successful JSON object")
        daily, units = payload["daily"], payload["daily_units"]
        if not isinstance(daily, dict) or not isinstance(units, dict):
            raise ValueError("daily and daily_units must be objects")
        expected_units = dict(zip(DAILY_FIELDS, ("°C", "°C", "mm")))
        for field, unit in expected_units.items():
            if units.get(field) != unit:
                raise ValueError(f"{field}: unexpected or missing unit")
        if units.get("time") != "iso8601":
            raise ValueError("time: expected iso8601")
        days = daily["time"]
        if not isinstance(days, list):
            raise ValueError("daily.time must be an array")
        for field in DAILY_FIELDS:
            if not isinstance(daily.get(field), list) or len(daily[field]) != len(days):
                raise ValueError(f"{field}: missing or misaligned daily array")
        offset = payload["utc_offset_seconds"]
        if isinstance(offset, bool) or not isinstance(offset, int):
            raise ValueError("utc_offset_seconds must be an integer")
        source_zone = ZoneInfo(payload["timezone"].strip())
        local_zone = ZoneInfo(location.timezone)
        forecasts = []
        for index, raw_day in enumerate(days):
            day = date.fromisoformat(raw_day.strip())
            if day.isoformat() != raw_day.strip():
                raise ValueError("daily.time must contain YYYY-MM-DD dates")
            # A fixed-offset aggregate is not a civil-day aggregate across DST.
            for boundary in (day, day + timedelta(days=1)):
                for zone in (local_zone, source_zone):
                    actual = datetime.combine(boundary, time.min, tzinfo=zone).utcoffset()
                    if actual != timedelta(seconds=offset):
                        raise ValueError("API fixed UTC offset does not match the local daily boundaries")
            forecasts.append(DailyForecast(
                location=location, forecast_date=day,
                temperature_min_c=daily["temperature_2m_min"][index],
                temperature_max_c=daily["temperature_2m_max"][index],
                precipitation_mm=daily["precipitation_sum"][index],
                source=WeatherSource.OPEN_METEO, collected_at=collected_at,
            ))
        return forecasts
    except (KeyError, ValueError, TypeError, AttributeError, OverflowError, ZoneInfoNotFoundError) as exc:
        raise OpenMeteoError(f"Invalid Open-Meteo daily response: {exc}") from exc


class OpenMeteoCollector:
    """Implementação estrutural de ForecastCollector para a API pública."""

    source = WeatherSource.OPEN_METEO
    URL = "https://api.open-meteo.com/v1/forecast"

    def __init__(self, client=None, *, now=None):
        self._client = OpenMeteoHttpClient() if client is None else client
        self._now = now or (lambda: datetime.now(timezone.utc))

    def collect(self, location: Location, start_date: date, end_date: date) -> list[DailyForecast]:
        if not isinstance(location, Location):
            raise ValueError("location must be a Location")
        for value in (start_date, end_date):
            if not isinstance(value, date) or isinstance(value, datetime):
                raise ValueError("Expected dates without a time")
        if start_date > end_date:
            raise ValueError("start_date must not exceed end_date")
        payload = self._client.get(self.URL, {
            "latitude": location.latitude, "longitude": location.longitude,
            "daily": ",".join(DAILY_FIELDS), "timezone": location.timezone,
            "temperature_unit": "celsius", "precipitation_unit": "mm",
            "timeformat": "iso8601", "start_date": start_date.isoformat(),
            "end_date": end_date.isoformat(),
        })
        return parse_daily_forecasts(payload, location, self._now())
