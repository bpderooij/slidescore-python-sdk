"""Tile-based polygon coordinate encoding/decoding.

Polygon vertices are split into tile jumps (omega-encoded) and within-tile
remainders (raw bytes), allowing efficient compression of spatially clustered
coordinate data.
"""

import array
import math
from io import BufferedWriter, BytesIO

from .containers import EfficientArray, FlatPolygonCoords
from ._omega_codec import OmegaEncoder


def encode_polygon(polygon: FlatPolygonCoords, tile_size: int):
    """Encode flat vertices into tile jumps + byte remainders.

    Since remainders are stored as raw bytes, *tile_size* must not exceed 256.
    """
    last_tile_x = 0
    last_tile_y = 0

    num_points_in_tile: list[int] = []
    x_jumps: list[int] = []
    y_jumps: list[int] = []
    remainders = array.array("B")

    for i in range(0, len(polygon), 2):
        point_x, point_y = polygon[i], polygon[i + 1]
        tile_x = math.floor(point_x / tile_size)
        tile_y = math.floor(point_y / tile_size)

        if (
            tile_x != last_tile_x
            or tile_y != last_tile_y
            or len(num_points_in_tile) == 0
        ):
            x_jumps.append(tile_x - last_tile_x)
            y_jumps.append(tile_y - last_tile_y)
            last_tile_x = tile_x
            last_tile_y = tile_y
            num_points_in_tile.append(1)
        else:
            num_points_in_tile[-1] += 1

        remainders.extend((point_x % tile_size, point_y % tile_size))

    return x_jumps, y_jumps, num_points_in_tile, remainders


def _max_tile_rows_cols(polygon: FlatPolygonCoords, tile_size: int) -> tuple[int, int]:
    """Return (num_rows, num_cols) needed to cover all points in *polygon*."""
    max_x, max_y = 0, 0
    for i in range(0, len(polygon), 2):
        max_x = max(polygon[i], max_x)
        max_y = max(polygon[i + 1], max_y)
    return math.ceil(max_y / tile_size), math.ceil(max_x / tile_size)


def _polygon_lengths_and_flat_vertices(polygons: EfficientArray):
    """Per-polygon vertex counts (from offset gaps) and the flat ``values_array``."""
    polygon_lengths = array.array("I")
    offsets = polygons.offset_array
    for i in range(1, len(offsets)):
        polygon_lengths.append(offsets[i] - offsets[i - 1])
    return polygon_lengths, polygons.values_array


def _dump_omega_array(fh: BufferedWriter, nums: list[int], encoding_type: str) -> None:
    """Omega-encode *nums* and write length-prefixed to *fh*."""
    encoded = OmegaEncoder().encode(nums, encoding_type)
    fh.write(encoded.nbytes.to_bytes(4, "little"))
    fh.write(encoded.tobytes())


def _dump_to_stream(
    fh: BufferedWriter,
    polygon_lengths: array.ArrayType,
    tile_size: int,
    num_rows: int,
    num_cols: int,
    encoded_polygon,
) -> None:
    """Write a complete encoded polygon blob to *fh*."""
    fh.write(tile_size.to_bytes(4, "little"))
    fh.write(num_rows.to_bytes(4, "little"))
    fh.write(num_cols.to_bytes(4, "little"))

    polygon_lengths_bytes = polygon_lengths.tobytes()
    fh.write(len(polygon_lengths_bytes).to_bytes(4, "little"))
    fh.write(polygon_lengths_bytes)

    x_jumps, y_jumps, num_points_in_tile, remainders = encoded_polygon

    _dump_omega_array(fh, x_jumps, "integers")
    _dump_omega_array(fh, y_jumps, "integers")
    _dump_omega_array(fh, num_points_in_tile, "naturalOnly")

    fh.write(len(remainders).to_bytes(4, "little"))
    fh.write(remainders.tobytes())


def polygons_to_bytes(polygons: EfficientArray, tile_size: int = 256) -> bytes:
    """Encode an ``EfficientArray`` of polygons into a binary blob."""
    polygon_lengths, combined = _polygon_lengths_and_flat_vertices(polygons)
    num_rows, num_cols = _max_tile_rows_cols(combined, tile_size)
    encoded = encode_polygon(combined, tile_size)

    buf = BytesIO()
    _dump_to_stream(buf, polygon_lengths, tile_size, num_rows, num_cols, encoded)
    return buf.getbuffer()
