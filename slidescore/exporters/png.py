"""PNG export for :class:`Heatmap` geometries."""

from __future__ import annotations

from slidescore.anno2._image_utils import encode_png
from slidescore.geometries import Heatmap

__all__ = ["to_png"]


def to_png(heatmap: Heatmap) -> bytes:
    """Encode a heatmap matrix as an 8-bit greyscale PNG."""
    rows, cols = heatmap.matrix.shape
    if rows == 0 or cols == 0:
        return encode_png([[0]], 1, 1, bitdepth=8)
    matrix = heatmap.matrix.tolist()
    return encode_png(matrix, cols, rows, bitdepth=8)
