"""Coletor HTML do Climatempo com cadastro de páginas restrito ao adaptador."""

import re
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date, datetime, timezone

from weather_rpa.domain import DailyForecast, Location, WeatherSource
from .climatempo_http import ClimatempoError, ClimatempoHttpClient
from .climatempo_parser import ClimatempoSelectors, parse_climatempo_forecasts


@dataclass(frozen=True)
class ClimatempoPage:
    """Identificação específica do site, independente do objeto de domínio."""

    city_code: int
    slug: str

    def __post_init__(self):
        if isinstance(self.city_code, bool) or not isinstance(self.city_code, int) or self.city_code <= 0:
            raise ValueError("city_code must be a positive integer")
        if not isinstance(self.slug, str) or not re.fullmatch(r"[a-z0-9]+(?:-[a-z0-9]+)*", self.slug):
            raise ValueError("slug must contain lowercase ASCII words separated by hyphens")

    @property
    def url(self) -> str:
        return f"https://www.climatempo.com.br/previsao-do-tempo/15-dias/cidade/{self.city_code}/{self.slug}"


class ClimatempoCollector:
    """Atende ForecastCollector sem navegador ou chamadas a endpoints privados."""

    source = WeatherSource.CLIMATEMPO

    def __init__(self, pages: Mapping[str, ClimatempoPage], client=None, *, selectors=None, now=None):
        self._pages = dict(pages)
        if any(not isinstance(page, ClimatempoPage) for page in self._pages.values()):
            raise ValueError("Every page must be a ClimatempoPage")
        self._client = ClimatempoHttpClient() if client is None else client
        self._selectors = ClimatempoSelectors() if selectors is None else selectors
        self._now = now or (lambda: datetime.now(timezone.utc))

    def collect(self, location: Location, start_date: date, end_date: date) -> list[DailyForecast]:
        if not isinstance(location, Location):
            raise ValueError("location must be a Location")
        for value in (start_date, end_date):
            if not isinstance(value, date) or isinstance(value, datetime):
                raise ValueError("Expected dates without a time")
        if start_date > end_date:
            raise ValueError("start_date must not exceed end_date")
        try:
            page = self._pages[location.location_id]
        except KeyError as exc:
            raise ClimatempoError(f"No page configured for {location.location_id}") from exc
        html = self._client.get(page.url)
        return parse_climatempo_forecasts(
            html, location, start_date, end_date, self._now(), self._selectors,
        )
