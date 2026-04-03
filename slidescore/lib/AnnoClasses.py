import array
import logging
from collections.abc import Sequence

from slidescore.lib.simplify import simplifyPolygons

logger = logging.getLogger(__name__)


class Points(Sequence):
    """Class that allows to store many points space-effeciently. Used to store a mask

    Can be indexed to a get a tuple of the n'th point."""

    def __init__(self, init_points: list = None):
        self.name = "points"
        self.flattened_points = array.array("I")
        self.metadata: dict[str, dict] = {}
        super().__init__()

        if init_points:
            for point in init_points:
                self.addPoint(point[0], point[1])

    def __getitem__(self, i: int):
        x = self.flattened_points[i * 2]
        y = self.flattened_points[(i * 2) + 1]
        return (x, y)

    def addPoint(self, x: int, y: int):
        self.flattened_points.extend([x, y])

    def __len__(self):
        return int(len(self.flattened_points) / 2)


class Polygons(Sequence):
    """Somewhat space effecient method of storing the positive and negative vertices from a polygon.

    Internally uses EfficientArray to store the positive vertices of each polygon"""

    def __init__(self):
        self.name = "polygons"
        self.polygons = EfficientArray()
        self.simplified_polygons = []
        self.negative_polygons_i = {}
        self.labels = []
        self.metadata: dict[int, dict] = {}
        super().__init__()

    def __getitem__(self, i: int | slice):
        """Retrieves a polygon from the values array and any associated negative polygons, if they are
        associated."""
        if isinstance(i, slice):
            start, stop, step = i.indices(len(self))
            return [self[index] for index in range(start, stop, step)]

        points_flat = self.polygons.getValues(i)
        postive_vertices = [
            (points_flat[j], points_flat[j + 1]) for j in range(0, len(points_flat), 2)
        ]
        return {
            "positiveVertices": postive_vertices,
            "negativeVerticesArr": (
                self.negative_polygons_i[i] if i in self.negative_polygons_i else None
            ),
        }

    def addPolygon(self, postive_vertices):
        """Add a polygon to the internal values array and return the index it was assigned"""
        self.polygons.addValues(postive_vertices)
        return len(self.polygons) - 1

    def linkPosPolygonToNegPolygon(self, pos_polygon_i, neg_polygon_i):
        """Store a connection between a positive polygon and a negative polygon, using indices"""
        if pos_polygon_i not in self.negative_polygons_i:
            self.negative_polygons_i[pos_polygon_i] = []
        self.negative_polygons_i[pos_polygon_i].append(neg_polygon_i)

    def simplify(self):
        """Simplifies the stored polygons to 1 px accuracy, and stores further simplified polygons lookup tables"""
        self.polygons = simplifyPolygons(self.polygons, 1)
        # Hard coded tolerance of 16 pixels for now
        self.simplified_polygons = simplifyPolygons(self.polygons, 16)

    def __len__(self):
        return len(self.polygons)  # Number of polygons present, pos & neg


class Heatmap:
    """Stores an x/y/value map of a heatmap"""

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
        # data is 2d matrix containing the pixels
        self.matrix = self.generate_2d_ubyte_array(len(data), len(data[0]))
        try:
            self.copy_matrix_to_larger(data, self.matrix)
        except (OverflowError, TypeError) as exc:
            raise ValueError("Heatmap values must be integers in range 0-255") from exc

        self.x_offset = x_offset
        self.y_offset = y_offset
        self.size_per_pixel = size_per_pixel
        self.name = name

        super().__init__()

    def setPoint(self, x: int, y: int, value: int):
        """Sets a point in the heatmap, increases matrix array if needed"""
        # First check if the current matrix can hold this xy
        current_size = len(self.matrix), len(self.matrix[0])
        # Matrix is indexed with [y][x]!
        max_y = max(current_size[0], y + 1)
        max_x = max(current_size[1], x + 1)

        if max_y > current_size[0] or max_x > current_size[1]:
            new_matrix = self.generate_2d_ubyte_array(max_y, max_x)
            self.copy_matrix_to_larger(self.matrix, new_matrix)
            self.matrix = new_matrix

        # Then simply assign the value
        self.matrix[y][x] = value

    def get_metadata(self):
        metadata = {}
        metadata["x"] = self.x_offset
        metadata["y"] = self.y_offset
        metadata["sizePerPixel"] = self.size_per_pixel
        return metadata

    def generate_2d_ubyte_array(self, num_rows, num_cols):
        """Generate a 2D array of type 'ubyte' with the specified number of rows and columns.
        Returns:
        - A 2D list of `array.array` of type 'B' (unsigned byte).
        """
        return [array.array("B", [0] * num_cols) for _ in range(num_rows)]

    def copy_matrix_to_larger(self, source, target):
        """Copies a smaller matrix into a larger one.

        The function assumes that the target matrix is large enough to contain the source matrix.
        """
        for i in range(len(source)):
            for j in range(len(source[0])):
                target[i][j] = source[i][j]

    @classmethod
    def from_numpy(
        cls, arr: "numpy.ndarray", x_offset: int, y_offset: int, size_per_pixel: int
    ) -> "Heatmap":
        """Construct a Heatmap from a 2-D numpy array.

        Parameters
        ----------
        arr : numpy.ndarray
            2-D array with shape ``(rows, cols)``. Values must be in 0-255.
            ``uint8`` arrays are accepted as-is; other integer/float dtypes are
            validated for range then cast to ``uint8``.
        x_offset : int
        y_offset : int
        size_per_pixel : int

        Returns
        -------
        Heatmap
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
        """Logical annotation count for Anno2 (`numItems`); not pixel/cell count."""
        return 1


class EfficientArray:
    """Efficient way to represent a array of arrays containing only unsigned integers"""

    def __init__(self):
        self.offsetArray = array.array("I")
        self.valuesArray = array.array("I")
        self.curOffsetIndex = 0

        self.offsetArray.append(0)

    def addValues(self, values):
        """Add a list of numbers, uint16t by default, to the current values array"""
        offset = self.offsetArray[self.curOffsetIndex]
        # Add the values and store the new offset

        self.valuesArray.extend(values)
        self.curOffsetIndex += 1
        self.offsetArray.append(offset + len(values))

    def getValues(self, i: int):
        """Retrieve an entry from the values array"""
        if i >= self.curOffsetIndex:
            logger.error("Trying to get i %s but max is %s", i, self.curOffsetIndex)
            return None
        start = self.offsetArray[i]
        end = self.offsetArray[i + 1]
        return self.valuesArray[start:end]

    def __len__(self):
        return self.curOffsetIndex


# Types
Items = Points | Polygons | Heatmap

# Single item
Point = list[int]  # Of len == 2
Polygon = dict[str, Points]  # With str == "positiveVertices" | "negativeVertices"
Item = Point | Polygon
