"""Shared type aliases for SlideScore wire data and anno2 containers."""

from __future__ import annotations

from typing import TypeAlias

from slidescore.anno2._stores import (
    TileRange,
    _HeatmapStore,
    _PointStore,
    _PolygonRow,
    _PolygonStore,
)
from slidescore.anno2._types import FlatPolygonCoords, PointCoord

# JSON values as returned by :meth:`requests.Response.json` / :func:`json.loads`.
JSONValue: TypeAlias = str | int | float | bool | None | list["JSONValue"] | dict[str, "JSONValue"]
JSONObject: TypeAlias = dict[str, JSONValue]

# SlideScore wire ``{x, y}`` dicts (integer coordinates after parsing).
SlideScoreCoordDict: TypeAlias = dict[str, int | float]
SlideScoreAnnotationJson: TypeAlias = JSONObject
SlideScorePointCoordJson: TypeAlias = JSONObject

# Query/form parameter values (omitted when ``None``).
APIParamValue: TypeAlias = str | int | float | bool | None
Anno2OptionalId: TypeAlias = int | str | None

# Decoded / encoded annotation layers (anno2 store union).
Anno2Items: TypeAlias = _PointStore | _PolygonStore | _HeatmapStore

# One element when iterating a :class:`~slidescore.anno2._stores._PointStore`.
SlidePoint2D: TypeAlias = PointCoord

# Single item when iterating a store. Points yield ``(x, y)`` tuples; polygon
# stores yield :class:`_PolygonRow` instances (raw exterior + interiors + metadata).
EncoderItem: TypeAlias = PointCoord | _PolygonRow

__all__ = [
    "APIParamValue",
    "Anno2Items",
    "Anno2OptionalId",
    "EncoderItem",
    "FlatPolygonCoords",
    "JSONValue",
    "JSONObject",
    "PointCoord",
    "SlidePoint2D",
    "SlideScoreAnnotationJson",
    "SlideScoreCoordDict",
    "SlideScorePointCoordJson",
    "TileRange",
]
