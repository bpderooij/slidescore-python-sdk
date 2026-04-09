from __future__ import annotations

import array
import logging
from collections.abc import Sequence

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

        points_flat = self.polygons.get_values(i)
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

    matrix: list
    x_offset: int
    y_offset: int
    size_per_pixel: int
    name: str

    def __init__(
        self,
        data: list,
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
    def _copy_matrix(source, target) -> None:
        """Copy *source* into the top-left corner of *target*."""
        for i in range(len(source)):
            for j in range(len(source[0])):
                target[i][j] = source[i][j]

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


class EfficientArray:
    """Efficient storage for a jagged array of unsigned integers."""

    def __init__(self):
        self.offset_array = array.array("I")
        self.values_array = array.array("I")
        self._cur_offset = 0
        self.offset_array.append(0)

    def add_values(self, values) -> None:
        """Append a group of values as a new entry."""
        offset = self.offset_array[self._cur_offset]
        self.values_array.extend(values)
        self._cur_offset += 1
        self.offset_array.append(offset + len(values))

    def get_values(self, i: int) -> array.array:
        """Retrieve the *i*-th entry from the jagged array."""
        if i >= self._cur_offset:
            raise IndexError(
                f"Index {i} out of range for EfficientArray of length {self._cur_offset}"
            )
        start = self.offset_array[i]
        end = self.offset_array[i + 1]
        return self.values_array[start:end]

    def __len__(self):
        return self._cur_offset


# Types
Items = Points | Polygons | Heatmap

# Single item
Point = list[int]  # Of len == 2
Polygon = dict[str, Points]  # With str == "positiveVertices" | "negativeVertices"
Item = Point | Polygon
