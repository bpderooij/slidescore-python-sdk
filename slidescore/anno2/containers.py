from __future__ import annotations

import array
import logging
from collections.abc import Sequence
from typing import NamedTuple, TypedDict

from slidescore.anno2._simplify import simplify_polygons

logger = logging.getLogger(__name__)


class Points(Sequence):
    """Space-efficient storage of 2-D points (mask or annotation).

    Can be indexed to get a ``(x, y)`` tuple for the *n*-th point.
    """

    def __init__(self, init_points: list | None = None):
        self.name = "points"
        self.flattened_points = array.array("I")
        self.metadata: dict[str, dict] = {}
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


class Polygons(Sequence):
    """Space-efficient storage of positive/negative polygon vertices.

    Internally uses ``EfficientArray`` for the flat coordinate data.
    """

    def __init__(self):
        self.name = "polygons"
        self.polygons = EfficientArray()
        self.simplified_polygons = []
        self.negative_polygons_i = {}
        self.labels = []
        self.metadata: dict[int, dict] = {}
        super().__init__()

    def __getitem__(self, i: int | slice):
        if isinstance(i, slice):
            start, stop, step = i.indices(len(self))
            return [self[index] for index in range(start, stop, step)]

        points_flat = self.polygons[i]
        positive_vertices = [
            (points_flat[j], points_flat[j + 1]) for j in range(0, len(points_flat), 2)
        ]
        return {
            "positiveVertices": positive_vertices,
            "negativeVerticesArr": (
                self.negative_polygons_i[i] if i in self.negative_polygons_i else None
            ),
        }

    def add_polygon(self, positive_vertices) -> int:
        """Add a polygon and return its index."""
        self.polygons.add_values(positive_vertices)
        return len(self.polygons) - 1

    def link_negative(self, pos_polygon_i: int, neg_polygon_i: int) -> None:
        """Link a negative (hole) polygon to a positive polygon by index."""
        if pos_polygon_i not in self.negative_polygons_i:
            self.negative_polygons_i[pos_polygon_i] = []
        self.negative_polygons_i[pos_polygon_i].append(neg_polygon_i)

    def simplify(self):
        """Simplify stored polygons to 1 px accuracy, and create further simplified copies for lookup tables."""
        self.polygons = simplify_polygons(self.polygons, 1)
        self.simplified_polygons = simplify_polygons(self.polygons, 16)

    def __len__(self):
        return len(self.polygons)


class Heatmap:
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
            raise ValueError("Heatmap values must be integers in range 0-255") from exc

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
        """Copy *source* into *target* row-wise (``__init__`` or ``set_point`` grow)."""
        for i, row in enumerate(source):
            ub = row if isinstance(row, array.array) and row.typecode == "B" else array.array("B", row)
            target[i][: len(ub)] = ub

    @classmethod
    def from_numpy(
        cls, arr: "numpy.ndarray", x_offset: int, y_offset: int, size_per_pixel: int
    ) -> Heatmap:
        """Construct a Heatmap from a 2-D numpy array.

        Parameters
        ----------
        arr : numpy.ndarray
            2-D array with shape ``(rows, cols)``. Values must be in 0–255.
            ``uint8`` arrays are accepted as-is; other dtypes are validated
            for range then cast.
        x_offset : int
        y_offset : int
        size_per_pixel : int
        """
        try:
            import numpy as np
        except ImportError as exc:
            raise ImportError("numpy is required for Heatmap.from_numpy") from exc

        if arr.ndim != 2:
            raise ValueError(f"Expected a 2-D array, got shape {arr.shape}")

        if arr.dtype != np.uint8:
            arr_min, arr_max = int(arr.min()), int(arr.max())
            if arr_min < 0 or arr_max > 255:
                raise ValueError(
                    f"Array values must be in range 0-255, got min={arr_min}, max={arr_max}"
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


# Types
class TileRange(NamedTuple):
    """Inclusive tile indices on the slide grid for an item bounding box.

    Used when binning points (masks, density lookups) and polygons
    (polygon container); not specific to either.
    """

    x_start: int
    y_start: int
    x_end: int
    y_end: int


Items = Points | Polygons | Heatmap

# One element when iterating ``Points`` (an ``(x, y)`` pair in slide coordinates).
Point = tuple[int, int]


class Polygon(TypedDict):
    """One polygon row in SlideScore wire shape (same as :meth:`Polygons.__getitem__`).

    Not to be confused with :class:`Polygons`, which holds many polygons.
    """

    positiveVertices: list[tuple[float, float]]
    negativeVerticesArr: list[int] | None


# Flat ``[x1, y1, x2, y2, ...]`` for omega / tile polygon encoding (unsigned ints).
FlatPolygonCoords = list[int]

Item = Point | Polygon
