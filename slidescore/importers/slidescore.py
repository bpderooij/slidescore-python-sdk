"""Parse SlideScore wire formats (answer JSON and TSV) into geometries.

The public entry points are :meth:`slidescore.annotations.Annotations.from_*`;
the functions here are the underlying parsers that return flat
:data:`~slidescore.annotations.LayerItem` lists. They are kept as module-level
helpers (rather than inlined into ``annotations.py``) so the wire-format
logic stays separable and the ``annotations`` module can keep the anno2
promotion/packing helpers without also holding several hundred lines of
JSON-parsing code.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any, cast

import numpy as np

from slidescore.annotations import Layer, LayerItem
from slidescore.geometries import (
    Color,
    Ellipse,
    Heatmap,
    MultiPolygon,
    Point,
    Polygon,
    Rectangle,
    SlideScoreLabel,
    parse_color,
)

__all__ = [
    "parse_slidescore_json",
    "parse_points_tsv",
    "parse_polygons_tsv",
    "parse_heatmap_tsv",
    "read_slidescore_json",
]


# ---------------------------------------------------------------------------
# labels parsing helpers (shared across polygon-like wire entries)
# ---------------------------------------------------------------------------


def _slide_caption_label_from_dict(d: dict[str, Any]) -> SlideScoreLabel:
    """Build a caption :class:`SlideScoreLabel` from one ``labels[]`` dict."""
    if "label" not in d:
        raise ValueError("caption dict requires key 'label'")
    when_raw = d.get("whenToShow", d.get("whentoshow"))
    if when_raw is None:
        raise ValueError("caption dict requires whenToShow or whentoshow")
    fs_raw = d.get("fontSize", d.get("fontsize"))
    if fs_raw is None:
        raise ValueError("caption dict requires fontSize or fontsize")
    try:
        return SlideScoreLabel(
            label=str(d["label"]),
            x=float(d["x"]),
            y=float(d["y"]),
            whenToShow=str(when_raw),
            fontsize=int(fs_raw),
        )
    except KeyError as exc:
        raise ValueError("caption dict requires keys label, x, y") from exc
    except (TypeError, ValueError) as exc:
        raise ValueError("caption dict: invalid numeric fields") from exc


def _parse_label_list(
    labels_obj: object,
) -> tuple[list[SlideScoreLabel], list[dict[str, Any]]]:
    """Split ``labels[]`` into caption rows and legacy ``{"name": …}`` dicts."""
    if not labels_obj:
        return [], []
    if not isinstance(labels_obj, (list, tuple)):
        raise TypeError("labels must be a list")
    captions: list[SlideScoreLabel] = []
    name_entries: list[dict[str, Any]] = []
    for item in labels_obj:
        if not isinstance(item, dict):
            raise TypeError(
                f"labels[] entries must be dicts, got {type(item).__name__}"
            )
        d = cast(dict[str, Any], item)
        if "x" in d and "y" in d and "label" in d:
            captions.append(_slide_caption_label_from_dict(d))
        elif "name" in d:
            name_entries.append(dict(d))
        else:
            raise ValueError(
                "labels[] entry must be a caption (x, y, label, …) or "
                f"a name dict (name, …), got keys {set(d.keys())!r}"
            )
    return captions, name_entries


def _sidecar_from_name_entries(
    name_entries: list[dict[str, Any]],
) -> dict[str, Any]:
    """Pull extra keys from the first ``{"name": …}`` dict, minus ``name`` / ``polygon_i``."""
    if not name_entries:
        return {}
    side = dict(name_entries[0])
    side.pop("name", None)
    side.pop("polygon_i", None)
    return side


@dataclass(frozen=True, slots=True)
class _WireExtras:
    """Fields pulled off a SlideScore answer-JSON entry that are shared by every shape type."""

    captions: list[SlideScoreLabel]
    color: Color | None
    area: str | None
    modified_on: str | None
    metadata: dict[str, Any]


def _polygon_like_wire_attrs(entry: dict[str, Any]) -> _WireExtras:
    """Extract captions, color, area, modifiedOn, and leftover metadata from an entry."""
    captions, name_entries = _parse_label_list(entry.get("labels"))
    meta = {str(k): v for k, v in _sidecar_from_name_entries(name_entries).items()}
    color = parse_color(entry.get("color"))
    if color is None:
        color = parse_color(meta.pop("color", None))
    area = entry.get("area")
    modified_on = entry.get("modifiedOn")
    return _WireExtras(
        captions=captions,
        color=color,
        area=None if area is None else str(area),
        modified_on=None if modified_on is None else str(modified_on),
        metadata=meta,
    )


def _attribute_brush_captions(
    captions: list[SlideScoreLabel], members: list[Polygon]
) -> None:
    """Append each brush caption to the member polygon whose exterior contains it.

    SlideScore places captions at author-picked slide-pixel coordinates, so
    the correct attribution is spatial, not positional: ``labels[0]`` is not
    necessarily the caption for ``positivePolygons[0]``. When a caption does
    not land inside any exterior (rare; typically only happens when a caption
    sits just outside a jagged boundary), it falls through to the member
    whose exterior vertex is closest to the caption, to keep anno2 packing
    deterministic.
    """
    if not members:
        return
    for caption in captions:
        owner = _find_containing_member(caption.x, caption.y, members)
        if owner is None:
            owner = _find_nearest_member(caption.x, caption.y, members)
        owner.slidescore_labels.append(caption)


def _find_containing_member(
    x: float, y: float, members: list[Polygon]
) -> Polygon | None:
    for member in members:
        if member.contains(x, y):
            return member
    return None


def _find_nearest_member(x: float, y: float, members: list[Polygon]) -> Polygon:
    best: Polygon = members[0]
    best_d2 = math.inf
    for member in members:
        for vx, vy in member.exterior:
            dx = vx - x
            dy = vy - y
            d2 = dx * dx + dy * dy
            if d2 < best_d2:
                best_d2 = d2
                best = member
    return best


# ---------------------------------------------------------------------------
# SlideScore answer JSON
# ---------------------------------------------------------------------------


def parse_slidescore_json(data: list[dict[str, Any]]) -> list[LayerItem]:
    """Parse a SlideScore annotation JSON payload into geometries.

    Supports ``point`` (untyped ``x``/``y`` dicts), ``polygon``, ``brush``,
    ``ellipse``, ``rectangle``, and ``heatmap`` entries. ``area`` and
    ``modifiedOn`` round-trip via first-class fields on :class:`Geometry`;
    ``labels[]`` caption rows become :class:`SlideScoreLabel`\\s on
    ``slidescore_labels``. One ``type: "brush"`` entry becomes one
    :class:`MultiPolygon`; its captions are attributed to the member that
    spatially contains each caption's ``(x, y)``.
    """
    if not isinstance(data, list):
        raise TypeError("Expected a list as data")
    if not data:
        raise ValueError("Data is an empty list, cannot convert")

    first = data[0]
    if "type" not in first:
        if "x" in first and "y" in first:
            return [
                Point(
                    x=float(entry["x"]),
                    y=float(entry["y"]),
                    color=parse_color(entry.get("color")),
                )
                for entry in data
            ]
        raise ValueError("Unsupported slidescore JSON: type not specified")

    if str(first["type"]).lower() == "heatmap":
        return [_parse_heatmap_entry(first)]

    out: list[LayerItem] = []
    for entry in data:
        entry_type = str(entry["type"]).lower()
        if entry_type == "polygon":
            out.append(_parse_polygon_entry(entry))
        elif entry_type == "brush":
            out.append(_parse_brush_entry(entry))
        elif entry_type == "ellipse":
            out.append(_parse_ellipse_entry(entry))
        elif entry_type in ("rectangle", "rect"):
            # SlideScore answer JSON uses "rect"; legacy wire payloads
            # sometimes spell it out as "rectangle".
            out.append(_parse_rectangle_entry(entry))
        else:
            raise ValueError(
                f'Unsupported slidescore JSON type: "{entry["type"]}" not supported'
            )
    return out


def _parse_heatmap_entry(entry: dict[str, Any]) -> Heatmap:
    x_offset = int(entry["x"]) if "x" in entry else 0
    y_offset = int(entry["y"]) if "y" in entry else 0
    matrix = np.array(
        [[int(v) for v in row] for row in entry["data"]], dtype=np.uint8
    )
    n_rows = matrix.shape[0]
    size_per_pixel = round(int(entry["height"]) / n_rows) if n_rows else 1
    return Heatmap(
        matrix=matrix,
        x_offset=x_offset,
        y_offset=y_offset,
        size_per_pixel=size_per_pixel,
        color=parse_color(entry.get("color")),
    )


def _parse_polygon_entry(entry: dict[str, Any]) -> Polygon:
    exterior = [
        (float(round(vertex["x"])), float(round(vertex["y"])))
        for vertex in entry["points"]
    ]
    extras = _polygon_like_wire_attrs(entry)
    return Polygon(
        exterior=exterior,
        color=extras.color,
        metadata=extras.metadata,
        area=extras.area,
        modified_on=extras.modified_on,
        slidescore_labels=extras.captions,
    )


def _parse_brush_entry(entry: dict[str, Any]) -> MultiPolygon:
    """Build a :class:`MultiPolygon` from a ``type: "brush"`` answer entry.

    Positive rings become :class:`Polygon` members; negative rings pool and
    are assigned to members via :meth:`Polygon.assign_holes` (vertex-in-exterior).
    Brush captions are attributed to the containing member rather than by
    index — see :func:`_attribute_brush_captions`. Brush-level ``area`` and
    ``modifiedOn`` live on the :class:`MultiPolygon` itself; individual
    positive rings carry no per-member timestamp on the wire.
    """
    pos_polys = entry["positivePolygons"]
    neg_polys = entry["negativePolygons"]
    members: list[Polygon] = []
    for ring in pos_polys:
        exterior = [
            (float(round(vertex["x"])), float(round(vertex["y"])))
            for vertex in ring
        ]
        members.append(Polygon(exterior=exterior))
    neg_rings: list[list[tuple[float, float]]] = [
        [(float(round(vertex["x"])), float(round(vertex["y"]))) for vertex in neg]
        for neg in neg_polys
    ]

    hole_pool = list(neg_rings)
    for member in members:
        member.assign_holes(hole_pool)

    captions, name_entries = _parse_label_list(entry.get("labels"))
    _attribute_brush_captions(captions, members)

    meta = {str(k): v for k, v in _sidecar_from_name_entries(name_entries).items()}
    color = parse_color(entry.get("color"))
    if color is None:
        color = parse_color(meta.pop("color", None))
    if color is not None:
        for member in members:
            member.color = color

    area = entry.get("area")
    modified_on = entry.get("modifiedOn")
    return MultiPolygon(
        members=members,
        color=color,
        metadata=meta,
        area=None if area is None else str(area),
        modified_on=None if modified_on is None else str(modified_on),
    )


def _parse_ellipse_entry(entry: dict[str, Any]) -> Ellipse:
    center = entry["center"]
    size = entry["size"]
    extras = _polygon_like_wire_attrs(entry)
    return Ellipse(
        center=(float(round(center["x"])), float(round(center["y"]))),
        size=(float(round(size["x"])), float(round(size["y"]))),
        color=extras.color,
        metadata=extras.metadata,
        area=extras.area,
        modified_on=extras.modified_on,
        slidescore_labels=extras.captions,
    )


def _parse_rectangle_entry(entry: dict[str, Any]) -> Rectangle:
    corner = entry["corner"]
    size = entry["size"]
    extras = _polygon_like_wire_attrs(entry)
    return Rectangle(
        corner=(float(round(corner["x"])), float(round(corner["y"]))),
        size=(float(round(size["x"])), float(round(size["y"]))),
        color=extras.color,
        metadata=extras.metadata,
        area=extras.area,
        modified_on=extras.modified_on,
        slidescore_labels=extras.captions,
    )


# ---------------------------------------------------------------------------
# TSV parsers
# ---------------------------------------------------------------------------


def parse_points_tsv(text: str) -> list[Point]:
    """Parse a points TSV (``x\\ty`` per line) into :class:`Point` geometries."""
    lines = [line for line in text.splitlines() if line.strip()]
    out: list[Point] = []
    for raw_line in lines:
        parts = raw_line.strip().split()
        if len(parts) < 2:
            continue
        out.append(Point(x=float(int(parts[0])), y=float(int(parts[1]))))
    return out


def parse_polygons_tsv(text: str) -> list[Polygon]:
    """Parse a polygons TSV (flat ``x y x y …`` per line) into :class:`Polygon`s."""
    lines = [line for line in text.splitlines() if line.strip()]
    out: list[Polygon] = []
    for raw_line in lines:
        parts = raw_line.strip().split()
        if len(parts) < 2:
            continue
        flat = [int(token) for token in parts]
        vertices = [
            (float(flat[index]), float(flat[index + 1]))
            for index in range(0, len(flat), 2)
        ]
        out.append(Polygon(exterior=vertices))
    return out


def parse_heatmap_tsv(text: str) -> list[Heatmap]:
    """Parse a heatmap or binary-heatmap TSV into a single-element list."""
    lines = [line for line in text.splitlines() if line.strip()]
    if not lines:
        raise ValueError("empty heatmap TSV")
    first_parts = lines[0].split()
    header = first_parts[0].lower()
    x_offset = int(first_parts[1])
    y_offset = int(first_parts[2])
    size_per_pixel = int(first_parts[3])
    body = lines[1:]
    max_y = 0
    max_x = 0
    if header == "heatmap":
        triples: list[tuple[int, int, int]] = []
        for line in body:
            line_parts = line.split()
            if len(line_parts) < 3:
                continue
            x = int(line_parts[0])
            y = int(line_parts[1])
            val = int(line_parts[2])
            triples.append((x, y, val))
            max_y = max(max_y, y + 1)
            max_x = max(max_x, x + 1)
        data = np.zeros((max_y, max_x), dtype=np.uint8)
        for x, y, val in triples:
            data[y, x] = val
        return [
            Heatmap(
                matrix=data,
                x_offset=x_offset,
                y_offset=y_offset,
                size_per_pixel=size_per_pixel,
            )
        ]

    if header == "binary-heatmap":
        pairs: list[tuple[int, int]] = []
        for line in body:
            line_parts = line.split()
            if len(line_parts) < 2:
                continue
            x = int(line_parts[0])
            y = int(line_parts[1])
            pairs.append((x, y))
            max_y = max(max_y, y + 1)
            max_x = max(max_x, x + 1)
        data = np.zeros((max_y, max_x), dtype=np.uint8)
        for x, y in pairs:
            data[y, x] = 255
        return [
            Heatmap(
                matrix=data,
                x_offset=x_offset,
                y_offset=y_offset,
                size_per_pixel=size_per_pixel,
                name="binary-heatmap",
            )
        ]

    raise ValueError(f"unsupported heatmap TSV header: {header!r}")


# ---------------------------------------------------------------------------
# Convenience: JSON → anno2 store
# ---------------------------------------------------------------------------


def read_slidescore_json(data: list[dict[str, Any]]) -> Any:
    """Parse SlideScore answer JSON directly into an anno2 store.

    Convenience wrapper over :func:`parse_slidescore_json` →
    :meth:`Annotations.to_anno2`'s packing helpers. Used by the
    ``ConvertAnnotationToAnno2`` local encoder in
    :mod:`slidescore.api.annotations`.
    """
    from slidescore.annotations import _layer_to_store

    items = parse_slidescore_json(data)
    layer = Layer(geometries=items)
    return _layer_to_store(layer)
