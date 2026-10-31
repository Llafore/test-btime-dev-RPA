"""Contratos estruturais das dependências externas do caso de uso."""

from collections.abc import Iterable
from datetime import date
from pathlib import Path
from typing import Protocol

from weather_rpa.domain import DailyForecast, Location, WeatherSource


class ForecastCollector(Protocol):
    """Uma fonte que entrega registros normalizados para o período inclusivo."""

    @property
    def source(self) -> WeatherSource:
        """Fonte que deve constar em todos os registros retornados."""
        ...

    def collect(
        self, location: Location, start_date: date, end_date: date,
    ) -> Iterable[DailyForecast]:
        """Obtém previsões da localidade, sem substituir a fonte silenciosamente."""
        ...


class ForecastExporter(Protocol):
    """Publicação de uma coleta completa e validada."""

    def export(self, forecasts: Iterable[DailyForecast], destination: str | Path) -> int:
        """Valida o artefato antes de publicar e retorna o total gravado.

        Falhas devem preservar o destino anterior. O diretório pai deve existir.
        """
        ...


class ForecastArtifactValidator(Protocol):
    """Validação do conteúdo efetivamente gravado no armazenamento."""

    def validate(self, path: str | Path) -> int:
        """Retorna o total validado ou lança erro se o artefato for inválido."""
        ...
