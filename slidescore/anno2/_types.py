"""Lightweight geometry type aliases for anno2 codecs (no container imports)."""

from __future__ import annotations

from typing import TypeAlias

__all__ = ["FlatPolygonCoords", "PointCoord"]

FlatPolygonCoords: TypeAlias = list[int]

PointCoord: TypeAlias = tuple[int, int]
