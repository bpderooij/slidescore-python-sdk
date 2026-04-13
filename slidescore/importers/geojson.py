"""Parse a GeoJSON FeatureCollection into :class:`Annotations`.

Each distinct ``properties.label`` becomes one :class:`Layer`; features
without a label land in the ``None`` layer. ``properties.color`` becomes
the per-geometry color; other ``properties`` keys end up on
:attr:`Geometry.metadata`.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from slidescore.annotations import Annotations, Layer, LayerItem
from slidescore.geometries import Color, Point, Polygon, parse_color

__all__ = ["parse_geojson"]


def parse_geojson(data: Mapping[str, Any]) -> Annotations:
    """Parse a GeoJSON FeatureCollection into :class:`Annotations`.

    Supports ``Point``, ``Polygon``, and ``MultiPolygon`` features. Polygon
    features may also carry a QuPath-style ``nucleusGeometry`` child polygon,
    which is treated as an additional feature under the same properties.
    Features with an unsupported geometry ``type`` are silently skipped.
    """
    annotations = Annotations()
    for feature in data.get("features", []):
        if not isinstance(feature, Mapping):
            continue
        geometry = feature.get("geometry")
        if not isinstance(geometry, Mapping):
            continue
        properties = feature.get("properties")
        properties_dict: dict[str, Any] = (
            dict(properties) if isinstance(properties, Mapping) else {}
        )
        row_meta, label, color = _split_properties(properties_dict)
        for geom_item in _geometries_from_feature(feature, geometry):
            item = _geometry_to_layer_item(
                geom_item, row_meta=row_meta, color=color
            )
            if item is None:
                continue
            _append_to_layer(annotations, label=label, color=color, item=item)
    return annotations


def _split_properties(
    properties: dict[str, Any],
) -> tuple[dict[str, Any], str | None, Color | None]:
    work = dict(properties)
    label_raw = work.pop("label", None)
    label = str(label_raw) if label_raw is not None else None
    color = parse_color(work.pop("color", None))
    return work, label, color


def _geometries_from_feature(
    feature: Mapping[str, Any], geometry: Mapping[str, Any]
) -> list[Mapping[str, Any]]:
    geoms: list[Mapping[str, Any]] = list(_expand_multipolygon(geometry))
    nucleus = feature.get("nucleusGeometry")
    if isinstance(nucleus, Mapping) and nucleus.get("type") == "Polygon":
        geoms.append(nucleus)
    return geoms


def _expand_multipolygon(
    geometry: Mapping[str, Any],
) -> list[Mapping[str, Any]]:
    if geometry.get("type") != "MultiPolygon":
        return [geometry]
    return [
        {"type": "Polygon", "coordinates": polygon}
        for polygon in geometry["coordinates"]
    ]


def _geometry_to_layer_item(
    geometry: Mapping[str, Any],
    *,
    row_meta: dict[str, Any],
    color: Color | None,
) -> LayerItem | None:
    geometry_type = geometry.get("type")
    if geometry_type == "Point":
        coords = geometry["coordinates"]
        return Point(
            x=float(round(coords[0])),
            y=float(round(coords[1])),
            color=color,
            metadata=dict(row_meta),
        )
    if geometry_type == "Polygon":
        rings = geometry["coordinates"]
        return Polygon(
            exterior=_ring_to_vertices(rings[0]),
            interiors=[_ring_to_vertices(r) for r in rings[1:]],
            color=color,
            metadata=dict(row_meta),
        )
    return None


def _append_to_layer(
    annotations: Annotations,
    *,
    label: str | None,
    color: Color | None,
    item: LayerItem,
) -> None:
    existing = annotations.layers.get(label)
    if existing is None:
        annotations.add_layer(
            Layer(label=label, color=color, geometries=[item])
        )
        return
    existing.geometries.append(item)


def _ring_to_vertices(ring: list[list[float]]) -> list[tuple[float, float]]:
    return [(float(round(xy[0])), float(round(xy[1]))) for xy in ring]


# MultiPolygon handling: parse_geojson walks each polygon as a separate feature
# by unwrapping before calling _geometry_to_layer_item.
def _expand_multipolygon(geometry: Mapping[str, Any]) -> list[Mapping[str, Any]]:
    if geometry.get("type") != "MultiPolygon":
        return [geometry]
    return [
        {"type": "Polygon", "coordinates": polygon}
        for polygon in geometry["coordinates"]
    ]
