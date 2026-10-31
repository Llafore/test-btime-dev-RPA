"""Handler do fluxo por HTML público."""

from weather_rpa.adapters.climatempo import ClimatempoCollector, ClimatempoPage
from weather_rpa.adapters.climatempo_http import ClimatempoHttpClient
from collections.abc import Iterable, Mapping
from datetime import date
from pathlib import Path

from weather_rpa.domain import Location
from weather_rpa.adapters.csv_artifact import CsvForecastExporter
from weather_rpa.application import CollectWeather, CollectionResult


def handle(
    locations: Iterable[Location], start_date: date, end_date: date,
    destination: str | Path, *, pages: Mapping[str, ClimatempoPage],
    timeout: float = 15.0, attempts: int = 3,
) -> CollectionResult:
    client = ClimatempoHttpClient(timeout=timeout, max_attempts=attempts)
    collector = ClimatempoCollector(pages, client=client)
    return CollectWeather(collector, CsvForecastExporter()).execute(
        locations, start_date, end_date, destination,
    )
