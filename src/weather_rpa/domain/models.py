"""Contrato dos dados normalizados, sem acesso a fontes externas."""

from dataclasses import dataclass
from datetime import date, datetime, timezone
from enum import Enum
from math import isfinite
from numbers import Real
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError


def _required_text(value: str, field: str) -> None:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field} must be a non-empty string")
    if value != value.strip():
        raise ValueError(f"{field} must not contain surrounding whitespace")


def _finite_number(value: float, field: str) -> None:
    # bool is numeric in Python, but is not a meteorological measurement.
    if isinstance(value, bool) or not isinstance(value, Real) or not isfinite(value):
        raise ValueError(f"{field} must be a finite number")


class WeatherSource(str, Enum):
    """Origem dos dados; o mecanismo de coleta não muda seu significado."""

    OPEN_METEO = "open_meteo"
    CLIMATEMPO = "climatempo"


@dataclass(frozen=True)
class Location:
    """Objeto de valor com os dados de uma localidade, sem cadastro persistido.

    location_id permite correlação interna, inclusive em coletas de várias
    cidades. Não é uma identidade persistente nem um identificador do provedor,
    não define sozinho a igualdade do objeto e não será exportado no CSV.
    """

    location_id: str
    name: str
    state: str
    latitude: float
    longitude: float
    timezone: str

    def __post_init__(self) -> None:
        for field in ("location_id", "name", "state", "timezone"):
            _required_text(getattr(self, field), field)
        if len(self.state) != 2 or not self.state.isascii() or not self.state.isalpha() or not self.state.isupper():
            raise ValueError("state must be a two-letter uppercase abbreviation")
        _finite_number(self.latitude, "latitude")
        _finite_number(self.longitude, "longitude")
        if not -90 <= self.latitude <= 90:
            raise ValueError("latitude must be between -90 and 90")
        if not -180 <= self.longitude <= 180:
            raise ValueError("longitude must be between -180 and 180")
        try:
            ZoneInfo(self.timezone)
        except (ZoneInfoNotFoundError, ValueError) as exc:
            raise ValueError("timezone must identify an available IANA time zone") from exc


@dataclass(frozen=True)
class DailyForecast:
    """Previsão de um dia civil no fuso da localidade.

    Precipitação é o acumulado previsto desse dia em mm, nunca probabilidade.
    None indica ausência de informação; zero é uma medida válida.
    O instante de coleta é normalizado para UTC sem alterar forecast_date.
    """

    location: Location
    forecast_date: date
    temperature_min_c: float
    temperature_max_c: float
    precipitation_mm: float | None
    source: WeatherSource
    collected_at: datetime

    def __post_init__(self) -> None:
        if not isinstance(self.location, Location):
            raise ValueError("location must be a Location")
        # datetime subclasses date, but a forecast day must not carry a time.
        if not isinstance(self.forecast_date, date) or isinstance(self.forecast_date, datetime):
            raise ValueError("forecast_date must be a date without a time")
        _finite_number(self.temperature_min_c, "temperature_min_c")
        _finite_number(self.temperature_max_c, "temperature_max_c")
        if self.temperature_min_c > self.temperature_max_c:
            raise ValueError("temperature_min_c must not exceed temperature_max_c")
        if self.precipitation_mm is not None:
            _finite_number(self.precipitation_mm, "precipitation_mm")
            if self.precipitation_mm < 0:
                raise ValueError("precipitation_mm must not be negative")
        if not isinstance(self.source, WeatherSource):
            raise ValueError("source must be a WeatherSource")
        if not isinstance(self.collected_at, datetime) or self.collected_at.utcoffset() is None:
            raise ValueError("collected_at must be a timezone-aware datetime")
        object.__setattr__(self, "collected_at", self.collected_at.astimezone(timezone.utc))
