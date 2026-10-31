"""Linha de comando: parâmetros, composição, logs e códigos de saída."""

import argparse
import logging
import math
from datetime import date, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from weather_rpa.configuration import load_locations
from weather_rpa.handlers.api import handle as handle_api
from weather_rpa.handlers.scraping import handle as handle_scraping
from weather_rpa.adapters.open_meteo_http import OpenMeteoError
from weather_rpa.adapters.climatempo_http import ClimatempoError

logger = logging.getLogger(__name__)


def _date(value):
    try:
        parsed = date.fromisoformat(value)
        if parsed.isoformat() != value:
            raise ValueError
        return parsed
    except ValueError as exc:
        raise argparse.ArgumentTypeError("Use YYYY-MM-DD") from exc


def _timeout(value):
    try:
        number = float(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("Timeout must be numeric") from exc
    if not math.isfinite(number) or number <= 0:
        raise argparse.ArgumentTypeError("Timeout must be positive and finite")
    return number


def _parser(mode):
    parser = argparse.ArgumentParser(description="Coleta diária de clima e exportação CSV validada.")
    if mode is None:
        group = parser.add_mutually_exclusive_group(required=True)
        group.add_argument("--api", action="store_const", const="api", dest="mode", help="Open-Meteo")
        group.add_argument("--scraping", action="store_const", const="scraping", dest="mode", help="HTML Climatempo")
    else:
        parser.set_defaults(mode=mode)
    parser.add_argument("--config", type=Path, help="JSON de localidades; padrão: São Paulo (sp)")
    parser.add_argument("--location", action="append", dest="location_ids", help="ID configurado; repetível; padrão: todas")
    parser.add_argument("--start-date", type=_date, help="Dia inicial; padrão: hoje no fuso local")
    parser.add_argument("--end-date", type=_date, help="Dia final inclusivo; padrão: dia inicial")
    parser.add_argument("--output", type=Path, help="CSV de destino; padrão: output/<fonte>.csv")
    parser.add_argument("--timeout", type=_timeout, default=15.0, help="Timeout de rede em segundos")
    parser.add_argument("--attempts", type=int, choices=range(1, 6), default=3, help="Máximo de tentativas HTTP (1 a 5)")
    parser.add_argument("--verbose", action="store_true", help="Logs detalhados e stack trace em erros")
    return parser


def main(argv=None, *, mode=None) -> int:
    parser = _parser(mode)
    args = parser.parse_args(argv)
    if args.end_date is not None and args.start_date is None:
        parser.error("--end-date requires --start-date")
    if args.start_date is not None and args.end_date is not None and args.start_date > args.end_date:
        parser.error("--start-date must not exceed --end-date")
    logging.basicConfig(level=logging.DEBUG if args.verbose else logging.INFO,
                        format="%(levelname)s %(message)s", force=True)
    try:
        catalog = load_locations(args.config)
        by_id = {location.location_id: location for location in catalog.locations}
        selected = args.location_ids or list(by_id)
        if len(set(selected)) != len(selected):
            raise ValueError("Repeated --location values are not allowed")
        if set(selected) - by_id.keys():
            raise ValueError("Unknown location IDs: " + ", ".join(sorted(set(selected) - by_id.keys())))
        locations = tuple(by_id[key] for key in selected)
        if args.mode == "scraping" and set(selected) - catalog.pages.keys():
            raise ValueError("Every selected scraping location must have a Climatempo page")
        start = args.start_date
        if start is None:
            today = {datetime.now(ZoneInfo(location.timezone)).date() for location in locations}
            if len(today) != 1:
                raise ValueError("Local dates differ; specify --start-date explicitly")
            start = today.pop()
        end = args.end_date or start
        destination = args.output or Path("output") / ("open_meteo.csv" if args.mode == "api" else "climatempo.csv")
        destination.parent.mkdir(parents=True, exist_ok=True)
        options = dict(timeout=args.timeout, attempts=args.attempts)
        if args.mode == "api":
            result = handle_api(locations, start, end, destination, **options)
        else:
            result = handle_scraping(locations, start, end, destination, pages=catalog.pages, **options)
        print(f"CSV salvo em {result.destination}: {result.record_count} registros, {result.location_count} localidades.")
        return 0
    except (OSError, ValueError, OpenMeteoError, ClimatempoError) as exc:
        logger.error("Coleta não concluída: %s", exc, exc_info=args.verbose)
        return 1
    except KeyboardInterrupt:
        logger.error("Coleta interrompida.")
        return 130


def api_main() -> int:
    return main(mode="api")


def scraping_main() -> int:
    return main(mode="scraping")
