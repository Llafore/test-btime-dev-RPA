"""Orquestração independente de fontes e formatos de armazenamento."""

from .collect_weather import CollectionError, CollectionResult, CollectWeather

__all__ = ["CollectWeather", "CollectionError", "CollectionResult"]
