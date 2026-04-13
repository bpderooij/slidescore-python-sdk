"""SlideScore annotations: slide-level container of labeled layers.

:class:`Annotations` is the slide-level object holding labeled layers and the
wire-format ``from_*`` / ``to_*`` entry points. :class:`Layer` is one label
channel: defaults plus a flat list of geometries that must be homogeneous in
*kind* (only points, only polygon-like shapes, or exactly one heatmap).

Geometries live in :mod:`slidescore.geometries` (a leaf module with zero
anno2 imports). Anno2 store types are imported only inside
:meth:`Annotations.from_anno2` / :meth:`Annotations.to_anno2`, and the
slidescore JSON / GeoJSON / TSV codecs live in the :mod:`slidescore.importers`
and :mod:`slidescore.exporters` subpackages.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any, Literal, TypeAlias

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

if TYPE_CHECKING:
    from slidescore.anno2._stores import _PolygonStore

__all__ = [
    "Annotations",
    "Layer",
    "LayerItem",
    "LayerMode",
    "RegionItem",
]

#: Anything that may appear inside a :class:`Layer`.
LayerItem: TypeAlias = (
    Point | Polygon | Rectangle | Ellipse | MultiPolygon | Heatmap
)

#: Polygon-like regions; brush strokes become :class:`MultiPolygon`.
RegionItem: TypeAlias = Polygon | Rectangle | Ellipse | MultiPolygon

LayerMode: TypeAlias = Literal["empty", "points", "regions", "heatmap"]

_REGION_TYPES: tuple[type, ...] = (Polygon, Rectangle, Ellipse, MultiPolygon)


def _validate_layer_geometries(items: list[LayerItem]) -> None:
    """Raise :class:`ValueError` if *items* mix incompatible kinds for one layer.

    Allowed:

    - Only :class:`Point` instances.
    - Any mix of region shapes (:class:`Polygon`, :class:`Rectangle`,
      :class:`Ellipse`, :class:`MultiPolygon`).
    - Exactly one :class:`Heatmap` and nothing else.
    """
    if not items:
        return
    has_heatmap = any(isinstance(x, Heatmap) for x in items)
    has_point = any(isinstance(x, Point) for x in items)
    has_region = any(isinstance(x, _REGION_TYPES) for x in items)
    if has_heatmap and len(items) > 1:
        raise ValueError("layer: heatmap must be the only geometry in its layer")
    if has_point and has_region:
        raise ValueError("layer: cannot mix points with region shapes")


@dataclass
class Layer:
    """One labeled channel: defaults plus a flat list of geometries.

    :attr:`label` and :attr:`color` are layer-level defaults — they are used
    when serializing geometries that don't carry their own
    :attr:`~slidescore.geometries.Geometry.label` /
    :attr:`~slidescore.geometries.Geometry.color`. See :meth:`effective_label`
    and :meth:`effective_color`.

    Geometries within a layer must be homogeneous in *kind*; see
    :func:`_validate_layer_geometries` for the rules.
    """

    label: str | None = None
    color: Color | None = None
    geometries: list[LayerItem] = field(default_factory=list)

    def __post_init__(self) -> None:
        _validate_layer_geometries(self.geometries)

    @property
    def mode(self) -> LayerMode:
        """Kind of geometries in this layer.

        Cheap: validation guarantees the layer is homogeneous, so the first
        item is enough to discriminate.
        """
        if not self.geometries:
            return "empty"
        first = self.geometries[0]
        if isinstance(first, Heatmap):
            return "heatmap"
        if isinstance(first, Point):
            return "points"
        return "regions"

    def effective_label(self, geometry: Geometry) -> str | None:
        """Geometry's own label, falling back to the layer label."""
        return geometry.label if geometry.label is not None else self.label

    def effective_color(self, geometry: Geometry) -> Color | None:
        """Geometry's own color, falling back to the layer color."""
        return geometry.color if geometry.color is not None else self.color


@dataclass
class Annotations:
    """Slide-level annotations: layers keyed by label, plus wire-format I/O.

    Keys are SlideScore label / class names; ``None`` is the unlabeled layer.
    """

    layers: dict[str | None, Layer] = field(default_factory=dict)

    # ------------------------------------------------------------------
    # Accessors
    # ------------------------------------------------------------------

    def __len__(self) -> int:
        return len(self.layers)

    def __contains__(self, label: object) -> bool:
        return label in self.layers

    def __getitem__(self, label: str | None) -> Layer:
        return self.layers[label]

    def add_layer(self, layer: Layer) -> None:
        """Insert *layer*, or extend the existing layer under the same label.

        When a layer with the same label already exists, the new geometries
        are appended after a compatibility check on the combined list; the
        existing layer's :attr:`~Layer.label` and :attr:`~Layer.color` are
        kept. Raises :class:`ValueError` if combining the geometries would
        produce an invalid (mixed-kind) layer.
        """
        existing = self.layers.get(layer.label)
        if existing is None:
            self.layers[layer.label] = layer
            return
        _validate_layer_geometries(existing.geometries + layer.geometries)
        existing.geometries.extend(layer.geometries)

    def single_layer(self) -> Layer:
        """Return the one and only layer, or raise if there are zero or several.

        Used by codecs (anno2, TSV) that can only represent one layer per file.
        """
        non_empty = [layer for layer in self.layers.values() if layer.geometries]
        if len(non_empty) == 0:
            raise ValueError("Annotations has no non-empty layers")
        if len(non_empty) > 1:
            raise ValueError(
                f"Annotations has {len(non_empty)} non-empty layers; this codec "
                "supports only one layer per file"
            )
        return non_empty[0]

    # ------------------------------------------------------------------
    # Wire-format constructors
    # ------------------------------------------------------------------

    @classmethod
    def from_slidescore_json(
        cls,
        data: list[dict[str, Any]],
        *,
        label: str | None = None,
        color: Color | None = None,
    ) -> Annotations:
        """Parse a SlideScore answer-JSON payload into geometries.

        SlideScore answer JSON is per-question, so the result is a single
        :class:`Layer` keyed by *label*. *label* and *color* become the
        layer-level defaults; per-shape values from the wire payload still
        win at serialization time via :meth:`Layer.effective_label` /
        :meth:`Layer.effective_color`.
        """
        from slidescore.importers.slidescore import parse_slidescore_json

        items = parse_slidescore_json(data)
        return cls(layers={label: Layer(label=label, color=color, geometries=items)})

    @classmethod
    def from_geojson(cls, data: dict[str, Any]) -> Annotations:
        """Parse a GeoJSON FeatureCollection into geometries.

        Layer label and color are inferred from feature properties; one
        layer is created per distinct label seen in the input.
        """
        from slidescore.importers.geojson import parse_geojson

        return parse_geojson(data)

    @classmethod
    def from_points_tsv(
        cls,
        text: str,
        *,
        label: str | None = None,
        color: Color | None = None,
    ) -> Annotations:
        """Parse a points TSV (``x\\ty`` per line) into a single layer."""
        from slidescore.importers.slidescore import parse_points_tsv

        items = parse_points_tsv(text)
        return cls(layers={label: Layer(label=label, color=color, geometries=items)})

    @classmethod
    def from_polygons_tsv(
        cls,
        text: str,
        *,
        label: str | None = None,
        color: Color | None = None,
    ) -> Annotations:
        """Parse a polygons TSV (flat ``x y x y …`` per line) into a single layer."""
        from slidescore.importers.slidescore import parse_polygons_tsv

        items = parse_polygons_tsv(text)
        return cls(layers={label: Layer(label=label, color=color, geometries=items)})

    @classmethod
    def from_heatmap_tsv(
        cls,
        text: str,
        *,
        label: str | None = None,
        color: Color | None = None,
    ) -> Annotations:
        """Parse a heatmap or binary-heatmap TSV into a single-heatmap layer."""
        from slidescore.importers.slidescore import parse_heatmap_tsv

        items = parse_heatmap_tsv(text)
        return cls(layers={label: Layer(label=label, color=color, geometries=items)})

    @classmethod
    def from_anno2(
        cls, path: str | Path, *, label: str | None = None
    ) -> Annotations:
        """Read an anno2 ZIP and promote raw rows to geometries.

        Anno2 files carry exactly one layer of annotations; the layer's
        class/question identity lives outside the ZIP, so the returned
        layer is keyed by *label* (default ``None``). Promotion of polygon
        rows to :class:`Polygon` / :class:`Rectangle` / :class:`Ellipse` (via
        the ``shape_overlay.json`` sidecar) lives here so that
        :mod:`slidescore.geometries` stays anno2-free.
        """
        from slidescore.anno2 import decode
        from slidescore.anno2._stores import (
            _HeatmapStore,
            _PointStore,
            _PolygonStore,
        )

        store = decode(path)
        if isinstance(store, _PointStore):
            items: list[LayerItem] = _points_store_to_geometries(store)
        elif isinstance(store, _PolygonStore):
            items = _polygon_store_to_geometries(store)
        elif isinstance(store, _HeatmapStore):
            items = [_heatmap_store_to_geometry(store)]
        else:
            raise TypeError(f"unsupported anno2 store type: {type(store).__name__}")
        return cls(layers={label: Layer(label=label, geometries=items)})

    # ------------------------------------------------------------------
    # Wire-format serializers
    # ------------------------------------------------------------------

    def to_slidescore_json(
        self, *, modified_on: str | None = None
    ) -> list[dict[str, Any]]:
        """Serialize every layer's geometries to a SlideScore JSON list."""
        from slidescore.exporters.slidescore import emit_slidescore_json

        return emit_slidescore_json(self, modified_on=modified_on)

    def to_geojson(self) -> dict[str, Any]:
        """Serialize polygon-like and point geometries to a GeoJSON FeatureCollection."""
        from slidescore.exporters.geojson import emit_geojson

        return emit_geojson(self)

    def to_slidescore_tsv(self) -> str:
        """Serialize this annotation set to a TSV string.

        Requires exactly one non-empty layer (points / polygons / heatmap).
        """
        from slidescore.exporters.slidescore import emit_slidescore_tsv

        return emit_slidescore_tsv(self)

    def to_anno2(
        self,
        path: str | Path,
        *,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        """Write geometries to an anno2 ZIP via the store layer.

        Anno2 archives hold one layer per file; if :attr:`layers` contains more
        than one non-empty layer, :class:`ValueError` is raised. Ellipses and
        rectangles round-trip via ``polygon_container/shape_overlay.json``;
        per-geometry SlideScore labels round-trip via ``labels.json``.
        """
        from slidescore.anno2 import encode

        layer = self.single_layer()
        store = _layer_to_store(layer)
        encode(store, path, metadata=metadata)


# ---------------------------------------------------------------------------
# Private anno2 promotion helpers
# ---------------------------------------------------------------------------
#
# These convert between the anno2 store layer (_PointStore, _PolygonStore,
# _HeatmapStore) and the domain geometry layer. All anno2 imports are local
# to keep geometries.py leaf.


def _normalize_wire_color(raw: object) -> Color | None:
    """Accept wire color payloads (str / list / tuple) and return a ``Color``."""
    if raw is None:
        return None
    if isinstance(raw, str):
        return raw.strip()
    if isinstance(raw, (list, tuple)) and len(raw) in (3, 4):
        try:
            return tuple(int(component) for component in raw)  # type: ignore[return-value]
        except (TypeError, ValueError):
            return None
    return None


def _pop_row_extras(
    raw_meta: dict[str, Any],
) -> tuple[Color | None, str | None, str | None]:
    """Strip the wire-level extras anno2 stashes in per-row metadata."""
    color = _normalize_wire_color(raw_meta.pop("color", None))
    area = raw_meta.pop("area", None)
    modified_on = raw_meta.pop("modifiedOn", None)
    return (
        color,
        None if area is None else str(area),
        None if modified_on is None else str(modified_on),
    )


def _points_store_to_geometries(store: Any) -> list[LayerItem]:
    out: list[LayerItem] = []
    for i in range(len(store)):
        x, y = store[i]
        raw_meta = dict(store.metadata.get(i, {}))
        color, area, modified_on = _pop_row_extras(raw_meta)
        out.append(
            Point(
                x=float(x),
                y=float(y),
                color=color,
                metadata=raw_meta,
                area=area,
                modified_on=modified_on,
            )
        )
    return out


def _heatmap_store_to_geometry(store: Any) -> Heatmap:
    import numpy as np

    meta = store.get_metadata()
    matrix = np.array([list(row) for row in store.matrix], dtype=np.uint8)
    return Heatmap(
        matrix=matrix,
        x_offset=int(meta["x"]),
        y_offset=int(meta["y"]),
        size_per_pixel=int(meta["sizePerPixel"]),
        name=store.name,
    )


def _collect_slidescore_labels_for_index(
    rows: list[dict[str, Any]], *, polygon_i: int
) -> list[SlideScoreLabel]:
    """Pull caption rows for one ``polygon_i`` out of ``labels.json`` contents."""
    captions: list[SlideScoreLabel] = []
    for entry in rows:
        if not isinstance(entry, dict):
            continue
        pi = entry.get("polygon_i")
        if pi is None or int(pi) != polygon_i:
            continue
        if "x" not in entry or "y" not in entry or "label" not in entry:
            continue
        when_raw = entry.get("whenToShow", entry.get("whentoshow"))
        if when_raw is None:
            raise ValueError("caption row requires whenToShow or whentoshow")
        fs_raw = entry.get("fontSize", entry.get("fontsize"))
        if fs_raw is None:
            raise ValueError("caption row requires fontSize or fontsize")
        captions.append(
            SlideScoreLabel(
                label=str(entry["label"]),
                x=float(entry["x"]),
                y=float(entry["y"]),
                whenToShow=str(when_raw),
                fontsize=int(fs_raw),
            )
        )
    return captions


def _promote_polygon_row(
    *,
    exterior: list[tuple[int, int]],
    interiors: list[list[tuple[int, int]]],
    metadata: dict[str, Any],
    slidescore_labels: list[SlideScoreLabel],
    shape_overlay: dict[str, Any] | None,
) -> Polygon | Rectangle | Ellipse:
    """Build a polygon-like geometry from an anno2 row.

    If *shape_overlay* (from ``polygon_container/shape_overlay.json``) marks
    this row as an ellipse or rectangle and the row has no interior rings,
    we return the typed shape. Otherwise we return a :class:`Polygon`.
    """
    base_meta = dict(metadata)
    color, area, modified_on = _pop_row_extras(base_meta)

    if shape_overlay is not None and not interiors:
        kind = shape_overlay.get("kind")
        if kind == "ellipse":
            center = shape_overlay.get("center")
            size = shape_overlay.get("size")
            if (
                isinstance(center, (list, tuple))
                and len(center) == 2
                and isinstance(size, (list, tuple))
                and len(size) == 2
            ):
                return Ellipse(
                    center=(float(center[0]), float(center[1])),
                    size=(float(size[0]), float(size[1])),
                    color=color,
                    metadata=base_meta,
                    area=area,
                    modified_on=modified_on,
                    slidescore_labels=list(slidescore_labels),
                )
        elif kind == "rectangle":
            corner = shape_overlay.get("corner")
            size = shape_overlay.get("size")
            if (
                isinstance(corner, (list, tuple))
                and len(corner) == 2
                and isinstance(size, (list, tuple))
                and len(size) == 2
            ):
                return Rectangle(
                    corner=(float(corner[0]), float(corner[1])),
                    size=(float(size[0]), float(size[1])),
                    color=color,
                    metadata=base_meta,
                    area=area,
                    modified_on=modified_on,
                    slidescore_labels=list(slidescore_labels),
                )
    return Polygon(
        exterior=[(float(x), float(y)) for x, y in exterior],
        interiors=[[(float(x), float(y)) for x, y in ring] for ring in interiors],
        color=color,
        metadata=base_meta,
        area=area,
        modified_on=modified_on,
        slidescore_labels=list(slidescore_labels),
    )


def _polygon_store_to_geometries(store: Any) -> list[LayerItem]:
    from typing import cast

    from slidescore.anno2._stores import _PolygonRow

    hole_indices: set[int] = set()
    for linked in store.negative_polygons_i.values():
        hole_indices.update(linked)

    out: list[LayerItem] = []
    for i in range(len(store)):
        if i in hole_indices:
            continue
        row = cast(_PolygonRow, store[i])
        captions = _collect_slidescore_labels_for_index(
            store.labels, polygon_i=i
        )
        out.append(
            _promote_polygon_row(
                exterior=row.exterior,
                interiors=row.interiors,
                metadata=row.metadata,
                slidescore_labels=captions,
                shape_overlay=store.shape_overlay.get(i),
            )
        )
    return out


# ---------------------------------------------------------------------------
# Private anno2 packing helpers (geometry → store)
# ---------------------------------------------------------------------------


def _flat_xy(vertices: list[tuple[float, float]]) -> list[int]:
    flat: list[int] = []
    for x, y in vertices:
        flat.append(int(round(x)))
        flat.append(int(round(y)))
    return flat


def _dump_slidescore_labels(
    store: _PolygonStore, polygon_i: int, geometry: Geometry
) -> None:
    for label in geometry.slidescore_labels:
        row = label.to_wire_dict()
        row["polygon_i"] = polygon_i
        store.labels.append(row)


def _row_metadata(layer: Layer, geometry: Geometry) -> dict[str, Any]:
    """Per-row anno2 metadata: user ``metadata`` + the wire extras.

    ``color`` / ``area`` / ``modifiedOn`` are promoted to first-class
    :class:`Geometry` fields but ride along in per-row metadata when
    going through the anno2 store (kept there for backward compatibility
    with existing ZIPs); :func:`_pop_row_extras` strips them out on read.
    """
    out: dict[str, Any] = dict(geometry.metadata)
    color = layer.effective_color(geometry)
    if color is not None:
        out["color"] = color
    if geometry.area is not None:
        out["area"] = geometry.area
    if geometry.modified_on is not None:
        out["modifiedOn"] = geometry.modified_on
    return out


def _pack_point_layer(layer: Layer) -> Any:
    from slidescore.anno2._stores import _PointStore

    points = _PointStore()
    for index, geometry in enumerate(layer.geometries):
        assert isinstance(geometry, Point)
        points.add_point(int(round(geometry.x)), int(round(geometry.y)))
        meta_out = _row_metadata(layer, geometry)
        if meta_out:
            points.metadata[index] = meta_out
    return points


def _pack_single_region(
    polygons: _PolygonStore,
    layer: Layer,
    geometry: Polygon | Rectangle | Ellipse,
    *,
    shared_area: str | None = None,
    shared_modified_on: str | None = None,
) -> int:
    """Append one region to *polygons* and return its positive ``polygon_i``.

    Shape-overlay entries are written for :class:`Ellipse` / :class:`Rectangle`
    so center/size/corner round-trip. Interior rings on a :class:`Polygon` are
    linked as negatives.

    ``shared_area`` / ``shared_modified_on`` come from an enclosing
    :class:`MultiPolygon` so every member row carries the brush-level
    ``area`` / ``modifiedOn`` in its per-row metadata.
    """
    if isinstance(geometry, Ellipse):
        as_polygon = geometry.to_polygon()
        pos_i = polygons.add_polygon(_flat_xy(as_polygon.exterior))
        cx, cy = geometry.center
        sx, sy = geometry.size
        polygons.shape_overlay[pos_i] = {
            "kind": "ellipse",
            "center": [int(round(cx)), int(round(cy))],
            "size": [int(round(sx)), int(round(sy))],
        }
    elif isinstance(geometry, Rectangle):
        as_polygon = geometry.to_polygon()
        pos_i = polygons.add_polygon(_flat_xy(as_polygon.exterior))
        corner_x, corner_y = geometry.corner
        sx, sy = geometry.size
        polygons.shape_overlay[pos_i] = {
            "kind": "rectangle",
            "corner": [int(round(corner_x)), int(round(corner_y))],
            "size": [int(round(sx)), int(round(sy))],
        }
    else:
        pos_i = polygons.add_polygon(_flat_xy(geometry.exterior))
        for hole in geometry.interiors:
            neg_i = polygons.add_polygon(_flat_xy(hole))
            polygons.link_negative(pos_i, neg_i)

    row_meta = _row_metadata(layer, geometry)
    if shared_area is not None and "area" not in row_meta:
        row_meta["area"] = shared_area
    if shared_modified_on is not None and "modifiedOn" not in row_meta:
        row_meta["modifiedOn"] = shared_modified_on
    polygons.metadata[pos_i] = row_meta
    _dump_slidescore_labels(polygons, pos_i, geometry)
    return pos_i


def _pack_polygon_layer(layer: Layer) -> _PolygonStore:
    """Pack region geometries into a :class:`_PolygonStore`.

    A :class:`MultiPolygon` fans out: each member becomes its own positive
    ``polygon_i`` (with linked negatives for its holes), and the brush-level
    ``area`` / ``modifiedOn`` are replicated onto each member row so they
    survive even if the MultiPolygon grouping is lost on the way back.
    Captions are already per-member by spatial attribution, so they travel
    with the right ``polygon_i``.
    """
    from slidescore.anno2._stores import _PolygonStore

    polygons = _PolygonStore()
    for geometry in layer.geometries:
        if isinstance(geometry, MultiPolygon):
            for member in geometry.members:
                _pack_single_region(
                    polygons,
                    layer,
                    member,
                    shared_area=geometry.area,
                    shared_modified_on=geometry.modified_on,
                )
        elif isinstance(geometry, (Polygon, Rectangle, Ellipse)):
            _pack_single_region(polygons, layer, geometry)
        else:
            raise TypeError(
                f"_pack_polygon_layer: unexpected geometry {type(geometry).__name__}"
            )
    return polygons


def _pack_heatmap_layer(layer: Layer) -> Any:
    from slidescore.anno2._stores import _HeatmapStore

    assert len(layer.geometries) == 1
    heatmap = layer.geometries[0]
    assert isinstance(heatmap, Heatmap)
    return _HeatmapStore.from_numpy(
        heatmap.matrix,
        int(round(heatmap.x_offset)),
        int(round(heatmap.y_offset)),
        int(round(heatmap.size_per_pixel)),
    )


def _layer_to_store(layer: Layer) -> Any:
    mode = layer.mode
    if mode == "points":
        return _pack_point_layer(layer)
    if mode == "regions":
        return _pack_polygon_layer(layer)
    if mode == "heatmap":
        return _pack_heatmap_layer(layer)
    raise ValueError(f"cannot encode empty layer to anno2 (mode={mode})")
