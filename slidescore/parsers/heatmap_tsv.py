from __future__ import annotations

from ..anno2.containers import Heatmap


def read_tsv_heatmap(path: str) -> Heatmap:
    """Read a heatmap from a TSV file.

    Expected format::

        Heatmap x_offset y_offset size_per_pixel
        x1 y1 value1
        x2 y2 value2
        ...
    """
    with open(path) as fh:
        first_line_parts = fh.readline().split()
        x_offset = int(first_line_parts[1])
        y_offset = int(first_line_parts[2])
        size_per_pixel = int(first_line_parts[3])

        prev_poss = fh.tell()
        max_y = 0
        max_x = 0
        for line in fh:
            line_parts = line.split()
            x, y = int(line_parts[0]), int(line_parts[1])
            max_y = max(max_y, y + 1)
            max_x = max(max_x, x + 1)

        fh.seek(prev_poss)

        data = [[0] * max_x for _ in range(max_y)]
        heatmap = Heatmap(data, x_offset, y_offset, size_per_pixel)
        for line in fh:
            line_parts = line.split()
            x, y, value = int(line_parts[0]), int(line_parts[1]), int(line_parts[2])
            heatmap.setPoint(x, y, value)

    return heatmap


def read_tsv_binary_heatmap(path: str) -> Heatmap:
    """Read a binary heatmap from a TSV file (value implicitly 255).

    Expected format::

        binary-heatmap x_offset y_offset size_per_pixel
        x1 y1
        x2 y2
        ...
    """
    with open(path) as fh:
        first_line_parts = fh.readline().split()
        x_offset = int(first_line_parts[1])
        y_offset = int(first_line_parts[2])
        size_per_pixel = int(first_line_parts[3])

        prev_poss = fh.tell()
        max_y = 0
        max_x = 0
        for line in fh:
            line_parts = line.split()
            x, y = int(line_parts[0]), int(line_parts[1])
            max_y = max(max_y, y + 1)
            max_x = max(max_x, x + 1)

        fh.seek(prev_poss)

        data = [[0] * max_x for _ in range(max_y)]
        heatmap = Heatmap(data, x_offset, y_offset, size_per_pixel, name="binary-heatmap")
        for line in fh:
            line_parts = line.split()
            x, y = int(line_parts[0]), int(line_parts[1])
            heatmap.setPoint(x, y, 255)

    return heatmap
