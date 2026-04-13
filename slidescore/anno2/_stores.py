"""Private storage primitives backing the anno2 codec.

These classes are an encoder/decoder implementation detail. They are
**not** the public domain model — that's :mod:`slidescore.geometries`,
exposed via the :class:`~slidescore.annotations.Annotations` collection.

The names start with an underscore for that reason. Nothing outside the
``slidescore.anno2`` package and the ``Annotations`` collection should
import from here.
"""

from __future__ import annotations

import array
import logging
from collections.abc import Sequence
from typing import Any, NamedTuple

from slidescore.anno2._simplify import simplify
from slidescore.anno2._types import FlatPolygonCoords

logger = logging.getLogger(__name__)


class TileRange(NamedTuple):
    """Inclusive tile indices on the slide grid for an item bounding box."""

    x_start: int
    y_start: int
    x_end: int
    y_end: int


class _PolygonRow(NamedTuple):
    """Raw polygon data as stored on disk for a single ``polygon_i``.

    Returned by :meth:`_PolygonStore.__getitem__`. Contains *no* label
    and *no* color — those live in side channels (``self.labels``,
    ``self.metadata``) and are joined back to the row by the
    ``Annotations`` layer.
    """

    exterior: list[tuple[int, int]]
    interiors: list[list[tuple[int, int]]]
    metadata: dict[str, Any]


class _PointStore(Sequence):
    """Space-efficient storage of 2-D points (mask or annotation).

    Indexable; the *n*-th element is a ``(x, y)`` tuple.
    """

    def __init__(self, init_points: list | None = None):
        self.name = "points"
        self.flattened_points = array.array("I")
        self.metadata: dict[int, dict] = {}
        super().__init__()

        if init_points:
            for point in init_points:
                self.add_point(point[0], point[1])

    def __getitem__(self, i: int):
        x = self.flattened_points[i * 2]
        y = self.flattened_points[(i * 2) + 1]
        return (x, y)

    def add_point(self, x: int, y: int) -> None:
        self.flattened_points.extend([x, y])

    def __len__(self):
        return len(self.flattened_points) // 2


class _PolygonStore(Sequence):
    """Space-efficient storage of positive/negative polygon vertices.

    Internally uses :class:`EfficientArray` for the flat coordinate data.
    Iteration / ``__getitem__`` yields :class:`_PolygonRow` instances —
    promotion to a domain-model :class:`~slidescore.geometries.Polygon`
    (or its sibling shapes) is the caller's responsibility.
    """

    def __init__(self):
        self.name = "polygons"
        self.polygons = EfficientArray()
        self.simplified_polygons = []
        self.negative_polygons_i: dict[int, list[int]] = {}
        self.labels: list[dict[str, Any]] = []
        self.metadata: dict[int, dict] = {}
        #: Maps positive ``polygon_i`` to overlay payload (``kind``, geometry fields)
        #: for ellipse/rectangle strokes. Written to ``shape_overlay.json`` in the ZIP.
        self.shape_overlay: dict[int, dict[str, Any]] = {}
        super().__init__()

    def __getitem__(self, i: int | slice) -> _PolygonRow | list[_PolygonRow]:
        if isinstance(i, slice):
            start, stop, step = i.indices(len(self))
            return [self[index] for index in range(start, stop, step)]

        points_flat = self.polygons[i]
        vertices = [
            (points_flat[j], points_flat[j + 1])
            for j in range(0, len(points_flat), 2)
        ]
        neg_indices = self.negative_polygons_i.get(i)
        interiors: list[list[tuple[int, int]]] = []
        if neg_indices:
            for ni in neg_indices:
                nc = self.polygons[ni]
                interiors.append(
                    [(nc[j], nc[j + 1]) for j in range(0, len(nc), 2)],
                )
        return _PolygonRow(
            exterior=vertices,
            interiors=interiors,
            metadata=dict(self.metadata.get(i, {})),
        )

    def add_polygon(self, positive_vertices) -> int:
        """Add a polygon and return its index."""
        self.polygons.add_values(positive_vertices)
        return len(self.polygons) - 1

    def link_negative(self, pos_polygon_i: int, neg_polygon_i: int) -> None:
        """Link a negative (hole) polygon to a positive polygon by index."""
        if pos_polygon_i not in self.negative_polygons_i:
            self.negative_polygons_i[pos_polygon_i] = []
        self.negative_polygons_i[pos_polygon_i].append(neg_polygon_i)

    def _simplify_polygons(self, tolerance: float = 1.0) -> None:
        result = EfficientArray()
        for polygon in self.polygons:
            result.add_values(simplify(polygon, tolerance))
        assert len(self.polygons) == len(result)
        if tolerance > 1:
            self.simplified_polygons = result
        else:
            self.polygons = result

    def simplify(self):
        """Simplify stored polygons in place; build a coarser lookup copy."""
        # Light pass: canonical vertex data stays on ``self.polygons``.
        self._simplify_polygons(1)
        # Heavy pass: coarser rings for the simplified-polygons ZIP stream.
        self._simplify_polygons(16)

    def __len__(self):
        return len(self.polygons)


class _HeatmapStore:
    """Stores an x/y/value heatmap as a 2-D matrix of unsigned bytes."""

    matrix: list[array.array]
    x_offset: int
    y_offset: int
    size_per_pixel: int
    name: str

    def __init__(
        self,
        data: Sequence[Sequence[int]],
        x_offset: int,
        y_offset: int,
        size_per_pixel: int,
        name: str = "heatmap",
    ):
        self.matrix = self._make_ubyte_matrix(len(data), len(data[0]))
        try:
            self._copy_matrix(data, self.matrix)
        except (OverflowError, TypeError) as exc:
            raise ValueError(
                "Heatmap values must be integers in range 0-255"
            ) from exc

        self.x_offset = x_offset
        self.y_offset = y_offset
        self.size_per_pixel = size_per_pixel
        self.name = name
        super().__init__()

    def set_point(self, x: int, y: int, value: int) -> None:
        """Set a point in the heatmap, expanding the matrix if needed."""
        current_h, current_w = len(self.matrix), len(self.matrix[0])
        new_h = max(current_h, y + 1)
        new_w = max(current_w, x + 1)

        if new_h > current_h or new_w > current_w:
            new_matrix = self._make_ubyte_matrix(new_h, new_w)
            self._copy_matrix(self.matrix, new_matrix)
            self.matrix = new_matrix

        self.matrix[y][x] = value

    def get_metadata(self) -> dict:
        return {
            "x": self.x_offset,
            "y": self.y_offset,
            "sizePerPixel": self.size_per_pixel,
        }

    @staticmethod
    def _make_ubyte_matrix(num_rows: int, num_cols: int) -> list[array.array]:
        return [array.array("B", [0] * num_cols) for _ in range(num_rows)]

    @staticmethod
    def _copy_matrix(
        source: Sequence[Sequence[int]],
        target: list[array.array],
    ) -> None:
        """Copy *source* into *target* row-wise (used by ``__init__`` / ``set_point``)."""
        for i, row in enumerate(source):
            ub = (
                row
                if isinstance(row, array.array) and row.typecode == "B"
                else array.array("B", row)
            )
            target[i][: len(ub)] = ub

    @classmethod
    def from_numpy(
        cls, arr: Any, x_offset: int, y_offset: int, size_per_pixel: int
    ) -> _HeatmapStore:
        """Construct a :class:`_HeatmapStore` from a 2-D numpy array.

        Parameters
        ----------
        arr : numpy.ndarray
            2-D array with shape ``(rows, cols)``. Values must be in 0-255.
            ``uint8`` arrays are accepted as-is; other dtypes are validated
            for range then cast.
        x_offset : int
        y_offset : int
        size_per_pixel : int
        """
        try:
            import numpy as np
        except ImportError as exc:
            raise ImportError(
                "numpy is required for _HeatmapStore.from_numpy"
            ) from exc

        if arr.ndim != 2:
            raise ValueError(f"Expected a 2-D array, got shape {arr.shape}")

        if arr.dtype != np.uint8:
            arr_min, arr_max = int(arr.min()), int(arr.max())
            if arr_min < 0 or arr_max > 255:
                raise ValueError(
                    f"Array values must be in range 0-255, got "
                    f"min={arr_min}, max={arr_max}"
                )
            arr = arr.astype(np.uint8)

        return cls(arr.tolist(), x_offset, y_offset, size_per_pixel)

    def __len__(self):
        """Logical annotation count for Anno2 (``numItems``); not pixel count."""
        return 1


class EfficientArray(Sequence[array.array]):
    """Jagged array of unsigned int rows (variable-length ``array.array`` per index).

    ``offset_array`` has length *n* + 1 for *n* rows: row *i* is
    ``values_array[offset_array[i] : offset_array[i + 1]]``.
    The row count is *n* (``len(offset_array) - 1``), not ``len(values_array)``
    (that is the total flat element count across all rows).

    Invariant after each ``add_values``: ``offset_array[-1] == len(values_array)``.
    """

    def __init__(self) -> None:
        self.offset_array = array.array("I", [0])
        self.values_array = array.array("I")

    def add_values(self, values) -> None:
        """Append a group of values as a new row."""
        offset_start = len(self.values_array)
        self.values_array.extend(values)
        self.offset_array.append(offset_start + len(values))

    def __getitem__(self, index: int | slice) -> array.array | list[array.array]:
        # n rows ⇒ n+1 cumulative offsets (offset_array[0] is always 0).
        n_rows = len(self.offset_array) - 1

        def row(row_index: int) -> array.array:
            i = row_index + n_rows if row_index < 0 else row_index
            if i < 0 or i >= n_rows:
                raise IndexError(
                    f"EfficientArray index {row_index} out of range (length {n_rows})"
                )
            offset_start = self.offset_array[i]
            offset_end = self.offset_array[i + 1]
            return self.values_array[offset_start:offset_end]

        if isinstance(index, slice):
            return [row(j) for j in range(*index.indices(n_rows))]
        if not isinstance(index, int):
            raise TypeError(
                f"EfficientArray indices must be int or slice, not {type(index).__name__}"
            )
        return row(index)

    def __len__(self) -> int:
        return len(self.offset_array) - 1


__all__ = [
    "EfficientArray",
    "FlatPolygonCoords",
    "TileRange",
    "_HeatmapStore",
    "_PointStore",
    "_PolygonRow",
    "_PolygonStore",
]
