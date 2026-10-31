"""Leitura e normalização da configuração externa dos pontos de entrada."""

import json
from dataclasses import dataclass
from importlib.resources import files
from pathlib import Path

from weather_rpa.adapters.climatempo import ClimatempoPage
from weather_rpa.domain import Location


@dataclass(frozen=True)
class LocationCatalog:
    locations: tuple[Location, ...]
    pages: dict[str, ClimatempoPage]


def load_locations(path: str | Path | None = None) -> LocationCatalog:
    """Carrega JSON local ou padrão empacotado; não acessa serviços externos."""
    text = (Path(path).read_text(encoding="utf-8") if path is not None else
            files("weather_rpa.config").joinpath("locations.json").read_text(encoding="utf-8"))
    data = json.loads(text)
    if not isinstance(data, dict) or set(data) != {"locations"}:
        raise ValueError("Configuration must contain only a locations array")
    if not isinstance(data["locations"], list) or not data["locations"]:
        raise ValueError("At least one configured location is required")
    required = {"location_id", "name", "state", "latitude", "longitude", "timezone"}
    locations, pages, ids, places = [], {}, set(), set()
    for entry in data["locations"]:
        if not isinstance(entry, dict) or not required <= entry.keys() or entry.keys() - required - {"climatempo"}:
            raise ValueError("Location configuration has missing or unknown fields")
        values = {key: entry[key] for key in required}
        for key in ("location_id", "name", "state", "timezone"):
            if isinstance(values[key], str):
                values[key] = values[key].strip()
        if isinstance(values["state"], str):
            values["state"] = values["state"].upper()
        location = Location(**values)
        place = (location.name, location.state, location.latitude, location.longitude, location.timezone)
        if location.location_id in ids or place in places:
            raise ValueError("Configured locations must have distinct internal IDs and values")
        ids.add(location.location_id)
        places.add(place)
        locations.append(location)
        if "climatempo" in entry:
            page = entry["climatempo"]
            if not isinstance(page, dict) or set(page) != {"city_code", "slug"}:
                raise ValueError("Climatempo configuration requires city_code and slug")
            slug = page["slug"].strip() if isinstance(page["slug"], str) else page["slug"]
            pages[location.location_id] = ClimatempoPage(page["city_code"], slug)
    return LocationCatalog(tuple(locations), pages)
