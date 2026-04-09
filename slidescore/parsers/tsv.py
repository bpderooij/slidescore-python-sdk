from __future__ import annotations

from ..anno2.containers import Heatmap, Points, Polygons
from .heatmap_tsv import read_tsv_binary_heatmap, read_tsv_heatmap


def read_tsv(path: str, points_type: str, support_experimental: bool = False):
    """Parse either points or polygons from a .tsv file on disk.

    Reads the first line to determine whether points or polygons are encoded.
    See :func:`read_tsv_points` and :func:`read_tsv_polygons` for format details.
    """
    with open(path) as fh:
        first_line = fh.readline()
        line_parts = first_line.split()

    are_points = len(line_parts) == 2
    is_heatmap = line_parts[0].lower() == "heatmap"
    is_binary_heatmap = line_parts[0].lower() == "binary-heatmap"
    if is_binary_heatmap and not support_experimental:
        raise ValueError(
            "Wanted to encode a binary heatmap but --experimental is not present"
        )

    if is_heatmap:
        items = read_tsv_heatmap(path)
    elif is_binary_heatmap:
        items = read_tsv_binary_heatmap(path)
    elif are_points:
        items = read_tsv_points(path)
        if points_type == "mask":
            items.name = "mask"
    else:
        items = read_tsv_polygons(path)

    if len(items) == 0:
        raise ValueError("No items loaded")

    return items


def read_tsv_points(path: str) -> Points:
    """Read points from a TSV file. One point (x y) per line."""
    items = Points()

    with open(path) as fh:
        for raw_line in fh:
            line_parts = raw_line.strip().split()
            if len(line_parts) < 2:
                continue
            x, y = int(line_parts[0]), int(line_parts[1])
            items.add_point(x, y)

    return items


def read_tsv_polygons(path: str) -> Polygons:
    """Read polygons from a TSV file. One polygon per line (x1 y1 x2 y2 …)."""
    items = Polygons()

    with open(path) as fh:
        for raw_line in fh:
            line_parts = raw_line.strip().split()
            if len(line_parts) < 2:
                continue
            cur_polygon = [int(point) for point in line_parts]
            items.add_polygon(cur_polygon)

    return items
