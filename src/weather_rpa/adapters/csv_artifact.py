"""Exportação e validação do contrato CSV de previsão diária."""

import csv
import json
import re
from collections.abc import Iterable
from datetime import date, datetime, timedelta
from importlib.resources import files
from math import isfinite
from pathlib import Path
from tempfile import NamedTemporaryFile

from weather_rpa.domain import DailyForecast, Location, WeatherSource
from weather_rpa.application.ports import ForecastArtifactValidator


class ArtifactValidationError(ValueError):
    """O arquivo não atende ao contrato de previsão diária."""


def load_forecast_schema() -> dict:
    """Lê o descriptor versionado, inclusive em instalações fora do repositório."""
    resource = files("weather_rpa.schemas").joinpath("daily_forecast.schema.json")
    return json.loads(resource.read_text(encoding="utf-8"))


def _parse_cell(raw: str, field: dict):
    name = field["name"]
    constraints = field.get("constraints", {})
    if raw == "":
        if constraints.get("required", False):
            raise ValueError(f"{name}: required value is missing")
        return None
    if raw != raw.strip():
        raise ValueError(f"{name}: surrounding whitespace is not allowed")

    kind = field["type"]
    if kind == "number":
        if not re.fullmatch(r"[+-]?(?:[0-9]+(?:\.[0-9]*)?|\.[0-9]+)(?:[eE][+-]?[0-9]+)?", raw):
            raise ValueError(f"{name}: expected a decimal number")
        value = float(raw)
        if not isfinite(value):
            raise ValueError(f"{name}: number must be finite")
    elif kind == "date":
        value = date.fromisoformat(raw)
        if value.isoformat() != raw:
            raise ValueError(f"{name}: expected YYYY-MM-DD")
    elif kind == "datetime":
        value = datetime.fromisoformat(raw)
        if value.utcoffset() != timedelta(0) or not raw.endswith("+00:00") or value.isoformat() != raw:
            raise ValueError(f"{name}: expected ISO 8601 datetime with UTC +00:00")
    elif kind == "string":
        value = raw
    else:
        raise ValueError(f"Unsupported contract type: {kind}")

    if "minimum" in constraints and value < constraints["minimum"]:
        raise ValueError(f"{name}: below minimum")
    if "maximum" in constraints and value > constraints["maximum"]:
        raise ValueError(f"{name}: above maximum")
    if "enum" in constraints and value not in constraints["enum"]:
        raise ValueError(f"{name}: unsupported value")
    if "pattern" in constraints and not re.fullmatch(constraints["pattern"], raw):
        raise ValueError(f"{name}: invalid format")
    return value


class CsvArtifactValidator:
    """Valida o subconjunto de Table Schema usado pelo contrato deste projeto.

    Verifica também as invariantes do domínio e o formato físico do CSV.
    Não é um validador genérico da especificação Table Schema completa.
    Erros de acesso ao arquivo permanecem OSError; conteúdo inválido gera
    ArtifactValidationError com a linha física onde foi detectado.
    """

    def validate(self, path: str | Path) -> int:
        """Relê um CSV UTF-8 e retorna a quantidade de registros válidos."""
        schema = load_forecast_schema()
        fields = schema["fields"]
        columns = [field["name"] for field in fields]
        seen = set()
        count = 0
        line = 1
        reader = None
        try:
            with Path(path).open(encoding="utf-8", newline="") as stream:
                reader = csv.reader(stream, strict=True)
                if next(reader, None) != columns:
                    raise ArtifactValidationError("line 1: unexpected CSV header or empty file")
                for cells in reader:
                    line = reader.line_num
                    if len(cells) != len(columns):
                        raise ValueError("unexpected number of columns")
                    row = {}
                    for raw, field in zip(cells, fields):
                        try:
                            row[field["name"]] = _parse_cell(raw, field)
                        except ValueError as exc:
                            raise ValueError(f"{field['name']}: {exc}") from exc
                    # Reuse domain rules without exposing an internal ID in the artifact.
                    location = Location(
                        location_id="artifact-validation", name=row["location_name"],
                        state=row["state"], latitude=row["latitude"],
                        longitude=row["longitude"], timezone=row["timezone"],
                    )
                    DailyForecast(
                        location=location, forecast_date=row["forecast_date"],
                        temperature_min_c=row["temperature_min_c"],
                        temperature_max_c=row["temperature_max_c"],
                        precipitation_mm=row["precipitation_mm"],
                        source=WeatherSource(row["source"]), collected_at=row["collected_at"],
                    )
                    key = tuple(row[name] for name in schema["primaryKey"])
                    if key in seen:
                        raise ValueError("duplicate forecast key")
                    seen.add(key)
                    count += 1
                if not count:
                    raise ArtifactValidationError("CSV must contain at least one forecast")
        except ArtifactValidationError:
            raise
        except (ValueError, csv.Error) as exc:
            if reader is not None:
                line = max(line, reader.line_num)
            raise ArtifactValidationError(f"line {line}: {exc}") from exc
        return count


class CsvForecastExporter:
    """Publica somente CSVs validados, preservando o destino em caso de falha."""

    def __init__(self, validator: ForecastArtifactValidator | None = None):
        self._validator = CsvArtifactValidator() if validator is None else validator

    def export(self, forecasts: Iterable[DailyForecast], destination: str | Path) -> int:
        """Grava, relê e valida antes de substituir o destino; retorna o total.

        O diretório pai deve existir. Não há append: cada arquivo representa
        uma coleta. A substituição ocorre no mesmo diretório/sistema de arquivos.
        """
        destination = Path(destination)
        schema = load_forecast_schema()
        columns = [field["name"] for field in schema["fields"]]
        temporary = None
        try:
            with NamedTemporaryFile(
                mode="w", encoding="utf-8", newline="", dir=destination.parent,
                prefix=f".{destination.name}.", suffix=".tmp", delete=False,
            ) as stream:
                temporary = Path(stream.name)
                writer = csv.DictWriter(stream, fieldnames=columns, lineterminator="\n")
                writer.writeheader()
                for forecast in forecasts:
                    if not isinstance(forecast, DailyForecast):
                        raise TypeError("Every exported item must be a DailyForecast")
                    location = forecast.location
                    writer.writerow({
                        "location_name": location.name,
                        "state": location.state,
                        "latitude": location.latitude,
                        "longitude": location.longitude,
                        "forecast_date": forecast.forecast_date.isoformat(),
                        "timezone": location.timezone,
                        "temperature_min_c": forecast.temperature_min_c,
                        "temperature_max_c": forecast.temperature_max_c,
                        "precipitation_mm": forecast.precipitation_mm,
                        "source": forecast.source.value,
                        "collected_at": forecast.collected_at.isoformat(),
                    })
            count = self._validator.validate(temporary)
            temporary.replace(destination)
            return count
        finally:
            if temporary is not None:
                temporary.unlink(missing_ok=True)
