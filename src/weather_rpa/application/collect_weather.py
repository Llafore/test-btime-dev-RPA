"""Caso de uso compartilhado pelos futuros handlers de API e scraping."""

import logging
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path

from weather_rpa.domain import DailyForecast, Location, WeatherSource
from .ports import ForecastCollector, ForecastExporter

logger = logging.getLogger(__name__)


class CollectionError(ValueError):
    """A fonte não entregou a cobertura ou os registros solicitados."""


@dataclass(frozen=True)
class CollectionResult:
    """Resumo devolvido ao chamador somente depois da publicação bem-sucedida."""

    destination: Path
    record_count: int
    location_count: int


class CollectWeather:
    """Coleta todas as localidades e verifica cobertura antes de exportar.

    Não consulta relógio, não escolhe provedor e não conhece CSV ou HTTP.
    Falhas de coleta/exportação são propagadas para o handler decidir a saída.
    """

    def __init__(self, collector: ForecastCollector, exporter: ForecastExporter):
        self._collector = collector
        self._exporter = exporter

    def execute(
        self, locations: Iterable[Location], start_date: date, end_date: date,
        destination: str | Path,
    ) -> CollectionResult:
        """Exige exatamente uma previsão por localidade e dia, incluindo limites."""
        for name, value in (("start_date", start_date), ("end_date", end_date)):
            if not isinstance(value, date) or isinstance(value, datetime):
                raise ValueError(f"{name} must be a date without a time")
        if start_date > end_date:
            raise ValueError("start_date must not exceed end_date")
        destination = Path(destination)
        locations = tuple(locations)
        if not locations:
            raise ValueError("At least one location is required")
        ids = set()
        places = set()
        for location in locations:
            if not isinstance(location, Location):
                raise ValueError("Every requested location must be a Location")
            place = (location.name, location.state, location.latitude,
                     location.longitude, location.timezone)
            if location.location_id in ids or place in places:
                raise ValueError("Requested locations must have distinct internal IDs and values")
            ids.add(location.location_id)
            places.add(place)
        source = self._collector.source
        if not isinstance(source, WeatherSource):
            raise ValueError("Collector source must be a WeatherSource")

        expected_days = (end_date - start_date).days + 1
        forecasts = []
        logger.info("Starting weather collection: source=%s locations=%d", source.value, len(locations))
        for location in locations:
            days = set()
            local_forecasts = []
            for forecast in self._collector.collect(location, start_date, end_date):
                if not isinstance(forecast, DailyForecast):
                    raise CollectionError(f"{location.location_id}: expected a DailyForecast")
                if forecast.location != location:
                    raise CollectionError(f"{location.location_id}: unexpected forecast location")
                if forecast.source != source:
                    raise CollectionError(f"{location.location_id}: unexpected forecast source")
                if not start_date <= forecast.forecast_date <= end_date:
                    raise CollectionError(f"{location.location_id}: forecast date outside requested period")
                if forecast.forecast_date in days:
                    raise CollectionError(f"{location.location_id}: duplicate forecast date")
                days.add(forecast.forecast_date)
                local_forecasts.append(forecast)
            if len(days) != expected_days:
                raise CollectionError(
                    f"{location.location_id}: incomplete date coverage; "
                    f"expected {expected_days}, received {len(days)}"
                )
            forecasts.extend(sorted(local_forecasts, key=lambda item: item.forecast_date))

        # The exporter owns artifact validation and publication as one operation.
        # Validating again here would happen too late, after replacing the destination.
        count = self._exporter.export(forecasts, destination)
        logger.info("Weather artifact published: destination=%s records=%d", destination, count)
        return CollectionResult(destination, count, len(locations))
