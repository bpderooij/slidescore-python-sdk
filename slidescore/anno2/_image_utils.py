import io

import png


def _make_zero_matrix(num_rows: int, num_cols: int):
    """Generate a zero-filled matrix of bytearrays."""
    return [bytearray(num_cols) for _ in range(num_rows)]


def encode_png(matrix, width: int, height: int, bitdepth: int = 1) -> bytes:
    """Encode a matrix of pixel values into a greyscale PNG."""
    writer = png.Writer(width, height, greyscale=True, bitdepth=bitdepth, compression=9)
    f = io.BytesIO()
    writer.write(f, matrix)
    f.seek(0)
    return f.read()


def _points_to_mask(points_arr, tile_size: int):
    """Turn a flat list of points into a 1-bit mask matrix."""
    matrix = _make_zero_matrix(tile_size, tile_size)
    for i in range(0, len(points_arr), 2):
        x = points_arr[i]
        y = points_arr[i + 1]
        matrix[y][x] = 1
    return matrix


def _points_to_png(points_arr, tile_size: int) -> bytes:
    """Encode a flat list of tile-local points into a 1-bit mask PNG."""
    matrix = _points_to_mask(points_arr, tile_size)
    return encode_png(matrix, tile_size, tile_size)


def _get_max_vals(lookup_table: dict) -> tuple[int, int, int]:
    """Return (max_x, max_y, max_value) from a nested tile lookup dict."""
    max_y = 0
    max_x = 0
    max_val = 0
    for y in lookup_table:
        max_y = max(max_y, y)
        for x in lookup_table[y]:
            max_x = max(max_x, x)
            max_val = max(max_val, lookup_table[y][x])
    return max_x, max_y, max_val


def lookup_table_to_png(lookup_table_container: dict) -> bytes:
    """Encode a density lookup table into an 8-bit greyscale PNG."""
    lookup_table = lookup_table_container["lookup"]
    max_x, max_y, max_val = _get_max_vals(lookup_table)
    width, height = max_x + 1, max_y + 1

    matrix = _make_zero_matrix(height, width)
    for y in lookup_table:
        for x in lookup_table[y]:
            matrix[y][x] = round((lookup_table[y][x] / max_val) * 255)

    return encode_png(matrix, width, height, 8)
