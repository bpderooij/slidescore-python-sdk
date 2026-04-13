"""Emit a GeoJSON FeatureCollection from :class:`Annotations`.

Heatmap layers are silently skipped — GeoJSON has no raster geometry. Ellipses
and rectangles are discretized to polygons via :meth:`to_polygon`, matching
what :func:`slidescore.importers.geojson.parse_geojson` can round-trip back.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from slidescore.annotations import Annotations, Layer
from slidescore.geometries import (
    Color,
    Ellipse,
    Geometry,
    Heatmap,
    MultiPolygon,
    Point,
    Polygon,
    Rectangle,
)

__all__ = ["emit_geojson"]


def _color_to_geojson(color: Color) -> str | list[int]:
    if isinstance(color, str):
        return color
    return list(color)


def _feature_properties(layer: Layer, geometry: Geometry) -> dict[str, Any]:
    props: dict[str, Any] = dict(geometry.metadata)
    label = layer.effective_label(geometry)
    if label is not None:
        props["label"] = label
    color = layer.effective_color(geometry)
    if color is not None:
        props["color"] = _color_to_geojson(color)
    if geometry.area is not None:
        props["area"] = geometry.area
    if geometry.modified_on is not None:
        props["modifiedOn"] = geometry.modified_on
    if geometry.slidescore_labels:
        props["labels"] = [
            caption.to_wire_dict() for caption in geometry.slidescore_labels
        ]
    return props


def emit_geojson(annotations: Annotations) -> dict[str, Any]:
    """Build a GeoJSON FeatureCollection from every layer in *annotations*.

    Per-layer :attr:`Layer.label` (question text) is written to
    ``feature.properties.label`` when set; per-geometry labels override
    the layer default. Heatmap geometries are skipped.
    """
    timestamp = (
        datetime.now(timezone.utc)
        .replace(microsecond=0)
        .isoformat()
        .replace("+00:00", "Z")
    )
    features: list[dict[str, Any]] = []
    for layer in annotations.layers.values():
        for geometry in layer.geometries:
            feature = _geometry_to_feature(layer, geometry)
            if feature is not None:
                features.append(feature)
    return {
        "type": "FeatureCollection",
        "features": features,
        "properties": {
            "exported_at": timestamp,
            "exported_from": "slidescore-anno2",
        },
    }


def _geometry_to_feature(
    layer: Layer, geometry: Geometry
) -> dict[str, Any] | None:
    if isinstance(geometry, Point):
        return {
            "type": "Feature",
            "geometry": {
                "type": "Point",
                "coordinates": [geometry.x, geometry.y],
            },
            "properties": _feature_properties(layer, geometry),
        }
    if isinstance(geometry, Polygon):
        coords: list[list[list[float]]] = [
            [[x, y] for x, y in geometry.exterior]
        ]
        for ring in geometry.interiors:
            coords.append([[x, y] for x, y in ring])
        return {
            "type": "Feature",
            "geometry": {"type": "Polygon", "coordinates": coords},
            "properties": _feature_properties(layer, geometry),
        }
    if isinstance(geometry, (Ellipse, Rectangle)):
        polygon = geometry.to_polygon()
        coords = [[[x, y] for x, y in polygon.exterior]]
        return {
            "type": "Feature",
            "geometry": {"type": "Polygon", "coordinates": coords},
            "properties": _feature_properties(layer, geometry),
        }
    if isinstance(geometry, MultiPolygon):
        multi_coords: list[list[list[list[float]]]] = []
        for member in geometry.members:
            rings: list[list[list[float]]] = [
                [[x, y] for x, y in member.exterior]
            ]
            for ring in member.interiors:
                rings.append([[x, y] for x, y in ring])
            multi_coords.append(rings)
        return {
            "type": "Feature",
            "geometry": {"type": "MultiPolygon", "coordinates": multi_coords},
            "properties": _feature_properties(layer, geometry),
        }
    if isinstance(geometry, Heatmap):
        return None
    raise TypeError(f"unsupported geometry type: {type(geometry).__name__}")
