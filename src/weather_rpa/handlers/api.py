"""Handler do fluxo por API pública."""

from collections.abc import Iterable
from datetime import date
from pathlib import Path

from weather_rpa.domain import Location
from weather_rpa.adapters.csv_artifact import CsvForecastExporter
from weather_rpa.adapters.open_meteo import OpenMeteoCollector
from weather_rpa.adapters.open_meteo_http import OpenMeteoHttpClient
from weather_rpa.application import CollectWeather, CollectionResult


def handle(
    locations: Iterable[Location], start_date: date, end_date: date,
    destination: str | Path, *, timeout: float = 15.0, attempts: int = 3,
) -> CollectionResult:
    client = OpenMeteoHttpClient(timeout=timeout, max_attempts=attempts)
    return CollectWeather(OpenMeteoCollector(client=client), CsvForecastExporter()).execute(
        locations, start_date, end_date, destination,
    )
