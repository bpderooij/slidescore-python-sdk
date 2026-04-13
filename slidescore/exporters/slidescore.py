"""Emit SlideScore wire formats (answer JSON, TSV) from :class:`Annotations`."""

from __future__ import annotations

from typing import Any, Iterable

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
    SlideScoreLabel,
)

__all__ = ["emit_slidescore_json", "emit_slidescore_tsv"]


def _xy_obj(x: float, y: float) -> dict[str, int]:
    return {"x": int(round(x)), "y": int(round(y))}


def _json_color(color: Color) -> str | list[int]:
    if isinstance(color, str):
        return color
    return list(color)


def _attach_color(obj: dict[str, Any], layer: Layer, geometry: Geometry) -> None:
    color = layer.effective_color(geometry)
    if color is not None:
        obj["color"] = _json_color(color)


def _attach_captions(
    obj: dict[str, Any], captions: Iterable[SlideScoreLabel]
) -> None:
    rows = [caption.to_wire_dict() for caption in captions]
    if rows:
        obj["labels"] = rows


def _attach_extras(
    obj: dict[str, Any],
    geometry: Geometry,
    *,
    include_area: bool,
    modified_on_override: str | None = None,
) -> None:
    """Attach ``area`` / ``modifiedOn`` from the geometry's first-class fields.

    ``modified_on_override`` lets :func:`emit_slidescore_json`'s caller stamp
    every emitted entry with a single timestamp (useful for batch uploads);
    otherwise each geometry's own :attr:`Geometry.modified_on` is written
    verbatim so parsed wire payloads round-trip.
    """
    modified_on = (
        modified_on_override
        if modified_on_override is not None
        else geometry.modified_on
    )
    if modified_on is not None:
        obj["modifiedOn"] = modified_on
    if include_area and geometry.area is not None:
        obj["area"] = geometry.area


# ---------------------------------------------------------------------------
# JSON
# ---------------------------------------------------------------------------


def emit_slidescore_json(
    annotations: Annotations,
    *,
    modified_on: str | None = None,
) -> list[dict[str, Any]]:
    """Serialize every layer in *annotations* to SlideScore answer JSON."""
    out: list[dict[str, Any]] = []
    for layer in annotations.layers.values():
        for geometry in layer.geometries:
            out.append(_geometry_to_json(layer, geometry, modified_on=modified_on))
    return out


def _geometry_to_json(
    layer: Layer, geometry: Geometry, *, modified_on: str | None
) -> dict[str, Any]:
    if isinstance(geometry, Point):
        obj: dict[str, Any] = _xy_obj(geometry.x, geometry.y)
        _attach_color(obj, layer, geometry)
        return obj
    if isinstance(geometry, MultiPolygon):
        return _multipolygon_to_brush(layer, geometry, modified_on=modified_on)
    if isinstance(geometry, Polygon):
        if geometry.interiors:
            # A lone polygon with holes serializes as a one-positive brush:
            # SlideScore has no "polygon with holes" wire variant.
            brush: dict[str, Any] = {
                "type": "brush",
                "positivePolygons": [
                    [_xy_obj(x, y) for x, y in geometry.exterior]
                ],
                "negativePolygons": [
                    [_xy_obj(x, y) for x, y in ring] for ring in geometry.interiors
                ],
            }
            _attach_captions(brush, geometry.slidescore_labels)
            _attach_color(brush, layer, geometry)
            _attach_extras(
                brush,
                geometry,
                include_area=True,
                modified_on_override=modified_on,
            )
            return brush
        poly: dict[str, Any] = {
            "type": "polygon",
            "points": [_xy_obj(x, y) for x, y in geometry.exterior],
        }
        _attach_captions(poly, geometry.slidescore_labels)
        _attach_color(poly, layer, geometry)
        _attach_extras(
            poly, geometry, include_area=True, modified_on_override=modified_on
        )
        return poly
    if isinstance(geometry, Ellipse):
        cx, cy = geometry.center
        sx, sy = geometry.size
        obj = {
            "type": "ellipse",
            "center": _xy_obj(cx, cy),
            "size": _xy_obj(sx, sy),
        }
        _attach_captions(obj, geometry.slidescore_labels)
        _attach_color(obj, layer, geometry)
        _attach_extras(
            obj, geometry, include_area=True, modified_on_override=modified_on
        )
        return obj
    if isinstance(geometry, Rectangle):
        corner_x, corner_y = geometry.corner
        width, height = geometry.size
        # SlideScore answer JSON spells rectangles as "rect" (see answer
        # exports); matching that keeps the importer/exporter symmetric
        # with what SlideScore itself produces.
        obj = {
            "type": "rect",
            "corner": _xy_obj(corner_x, corner_y),
            "size": _xy_obj(width, height),
        }
        _attach_captions(obj, geometry.slidescore_labels)
        _attach_color(obj, layer, geometry)
        _attach_extras(
            obj, geometry, include_area=True, modified_on_override=modified_on
        )
        return obj
    if isinstance(geometry, Heatmap):
        rows = int(geometry.matrix.shape[0])
        height_px = int(rows * geometry.size_per_pixel)
        obj = {
            "type": "heatmap",
            "x": int(round(geometry.x_offset)),
            "y": int(round(geometry.y_offset)),
            "height": height_px,
            "data": geometry.matrix.tolist(),
        }
        _attach_color(obj, layer, geometry)
        return obj
    raise TypeError(f"unsupported geometry type: {type(geometry).__name__}")


def _multipolygon_to_brush(
    layer: Layer, multi: MultiPolygon, *, modified_on: str | None
) -> dict[str, Any]:
    """Serialize a :class:`MultiPolygon` as one SlideScore ``brush`` entry.

    Positives are the members' exteriors in order; negatives are the
    concatenation of every member's interior rings. Captions from all
    members are flattened — each caption carries its own ``(x, y)`` so
    SlideScore renders them at the author-picked position, and the
    importer re-attributes them spatially on read.
    """
    brush: dict[str, Any] = {
        "type": "brush",
        "positivePolygons": [
            [_xy_obj(x, y) for x, y in member.exterior] for member in multi.members
        ],
        "negativePolygons": [
            [_xy_obj(x, y) for x, y in ring]
            for member in multi.members
            for ring in member.interiors
        ],
    }
    captions: list[SlideScoreLabel] = []
    for member in multi.members:
        captions.extend(member.slidescore_labels)
    _attach_captions(brush, captions)
    _attach_color(brush, layer, multi)
    _attach_extras(
        brush, multi, include_area=True, modified_on_override=modified_on
    )
    return brush


# ---------------------------------------------------------------------------
# TSV
# ---------------------------------------------------------------------------


def emit_slidescore_tsv(annotations: Annotations) -> str:
    """Serialize the one-and-only layer in *annotations* as TSV.

    - Points: one ``x\\ty`` line per point.
    - Regions: one flat ``x\\ty\\tx\\ty\\t…`` line per polygon. Ellipses and
      rectangles are discretized to polygon exteriors first;
      :class:`MultiPolygon` strokes emit one line per member. **Interior
      rings (holes) are lost** — SlideScore's polygon TSV upload format
      has no hole syntax; round-trip fidelity for brushes goes through
      the JSON / anno2 paths, not TSV.
    - Heatmap: the ``Heatmap`` / ``binary-heatmap`` header plus sparse rows.
    """
    layer = annotations.single_layer()
    mode = layer.mode
    if mode == "points":
        return "".join(
            f"{int(round(p.x))}\t{int(round(p.y))}\n"
            for p in layer.geometries
            if isinstance(p, Point)
        )
    if mode == "regions":
        lines: list[str] = []
        for geometry in layer.geometries:
            for polygon in _region_to_polygons(geometry):
                lines.append(_polygon_tsv_line(polygon))
        return "".join(lines)
    if mode == "heatmap":
        heatmap = layer.geometries[0]
        assert isinstance(heatmap, Heatmap)
        return _heatmap_to_tsv(heatmap)
    raise ValueError("emit_slidescore_tsv: layer is empty")


def _region_to_polygons(geometry: Geometry) -> list[Polygon]:
    if isinstance(geometry, Polygon):
        return [geometry]
    if isinstance(geometry, (Ellipse, Rectangle)):
        return [geometry.to_polygon()]
    if isinstance(geometry, MultiPolygon):
        return list(geometry.members)
    raise TypeError(
        f"emit_slidescore_tsv: unexpected geometry {type(geometry).__name__}"
    )


def _polygon_tsv_line(polygon: Polygon) -> str:
    return (
        "\t".join(
            f"{int(round(x))}\t{int(round(y))}" for x, y in polygon.exterior
        )
        + "\n"
    )


def _heatmap_to_tsv(heatmap: Heatmap) -> str:
    x_offset = int(round(heatmap.x_offset))
    y_offset = int(round(heatmap.y_offset))
    size_per_pixel = int(round(heatmap.size_per_pixel))
    is_binary = heatmap.name == "binary-heatmap"
    header_name = "binary-heatmap" if is_binary else "Heatmap"
    header = (
        f"{header_name} {x_offset} {y_offset} {size_per_pixel}"
        " # x_offset y_offset size_per_pixel\n"
    )
    parts: list[str] = [header]
    matrix = heatmap.matrix
    rows, cols = matrix.shape
    for y in range(rows):
        row = matrix[y]
        for x in range(cols):
            val = int(row[x])
            if val == 0:
                continue
            if is_binary:
                parts.append(f"{x}\t{y}\n")
            else:
                parts.append(f"{x}\t{y}\t{val}\n")
    return "".join(parts)
