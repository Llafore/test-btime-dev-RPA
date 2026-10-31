"""Seletores do layout e interpretação de HTML, sem transporte ou relógio."""

import json
import re
import unicodedata
from dataclasses import dataclass
from datetime import date, datetime, timedelta

from bs4 import BeautifulSoup

from weather_rpa.domain import DailyForecast, Location, WeatherSource
from .climatempo_http import ClimatempoError


@dataclass(frozen=True)
class ClimatempoSelectors:
    """Conhecimento do layout mantido separado das operações de extração."""

    root: str = "#mainContent"
    heading: str = "h1"
    calendar: str = "#calendar[data-infos]"
    calendar_attribute: str = "data-infos"
    cards: str = "section.accordion-card.-daily-infos"
    day: str = ".date-inside-circle__day"
    temperature_min: str = ".agg-daily__temps .agg-daily__temp.-min"
    temperature_max: str = ".agg-daily__temps .agg-daily__temp.-max"
    precipitation: str = ".agg-daily__rain-text"


def _normalized_name(value: str) -> str:
    return " ".join(unicodedata.normalize("NFKD", value).encode("ascii", "ignore").decode().casefold().split())


def _one(parent, selector: str):
    nodes = parent.select(selector)
    if len(nodes) != 1:
        raise ValueError(f"Expected exactly one component: {selector}")
    return nodes[0]


def _measurement(text: str, unit: str, *, optional=False) -> float | None:
    text = " ".join(text.replace("−", "-").split())
    if optional and text.casefold() in ("", "-", "—", "sem dados", "indisponível"):
        return None
    suffix = r"°\s*C?" if unit == "temperature" else r"mm"
    match = re.fullmatch(r"([+-]?[0-9]+(?:[.,][0-9]+)?)\s*" + suffix, text, re.IGNORECASE)
    if match is None:
        raise ValueError(f"Invalid {unit} measurement: {text!r}")
    return float(match[1].replace(",", "."))


def parse_climatempo_forecasts(
    html: str, location: Location, start_date: date, end_date: date,
    collected_at: datetime, selectors: ClimatempoSelectors | None = None,
) -> list[DailyForecast]:
    """Lê só os valores dos dias solicitados, cruzando cards e calendário.

    Datas completas vêm do atributo HTML do calendário, não do relógio nem da
    posição relativa ao dia atual. Campos de chuva em % nunca são usados como mm.
    """
    selectors = selectors or ClimatempoSelectors()
    try:
        soup = BeautifulSoup(html, "html.parser")
        title = soup.title.get_text(" ", strip=True).casefold() if soup.title else ""
        if soup.select_one("#challenge-form, .g-recaptcha, form[action*='captcha']") or any(
            marker in title for marker in ("just a moment", "access denied", "captcha")
        ):
            raise ValueError("Access challenge detected; no bypass attempted")
        root = _one(soup, selectors.root)
        heading = _one(root, selectors.heading).get_text(" ", strip=True)
        city = re.fullmatch(r"Previsão do Tempo para 15 Dias em (.+)\s+\(([A-Za-z]{2})\)", heading)
        if city is None or _normalized_name(city[1]) != _normalized_name(location.name) or city[2].upper() != location.state:
            raise ValueError("Page city does not match the requested location")
        calendar = _one(root, selectors.calendar)
        infos = json.loads(calendar[selectors.calendar_attribute])
        cards = root.select(selectors.cards)
        if not isinstance(infos, list) or not infos or len(infos) != len(cards):
            raise ValueError("Calendar and daily cards are missing or misaligned")
        result = []
        previous = None
        for info, card in zip(infos, cards):
            raw_date = info["date"].strip()
            day = date.fromisoformat(raw_date)
            if day.isoformat() != raw_date or (previous is not None and day != previous + timedelta(days=1)):
                raise ValueError("Calendar dates must be consecutive YYYY-MM-DD dates")
            previous = day
            visible_day = _one(card, selectors.day).get_text(strip=True)
            if not re.fullmatch(r"[0-9]{1,2}", visible_day) or int(visible_day) != day.day:
                raise ValueError("Daily card date does not match the calendar")
            if not start_date <= day <= end_date:
                continue
            if card.get("data-weather-state") != "success":
                raise ValueError("Requested daily card is unavailable")
            low = _one(card, selectors.temperature_min).get_text(" ", strip=True)
            high = _one(card, selectors.temperature_max).get_text(" ", strip=True)
            rain = _one(card, selectors.precipitation).get_text(" ", strip=True)
            result.append(DailyForecast(
                location=location, forecast_date=day,
                temperature_min_c=_measurement(low, "temperature"),
                temperature_max_c=_measurement(high, "temperature"),
                precipitation_mm=_measurement(rain, "precipitation", optional=True),
                source=WeatherSource.CLIMATEMPO, collected_at=collected_at,
            ))
        return result
    except (ValueError, KeyError, TypeError, AttributeError, OverflowError) as exc:
        raise ClimatempoError(f"Invalid Climatempo HTML: {exc}") from exc
