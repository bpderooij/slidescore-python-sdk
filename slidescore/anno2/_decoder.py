"""Anno2 ZIP decoder.

Decodes Anno2 archives into ``Points``, ``Polygons``, or ``Heatmap`` objects.
Polygon decoding adapted from slideforge-dev ``anno2_geometries.py``.
"""

from __future__ import annotations

import array
import io
import json
import logging
import tarfile
import zipfile

import brotli
import png
from bitarray import bitarray
from packaging import version

from slidescore.types import Anno2Items

from ._omega_codec import OmegaEncoder
from ._stores import _HeatmapStore, _PointStore, _PolygonStore

_logger = logging.getLogger(__name__)

_SUPPORTED_TYPES = {"polygons", "points", "mask", "heatmap", "binary-heatmap"}


# ---------------------------------------------------------------------------
# Low-level binary helpers
# ---------------------------------------------------------------------------


def _read_omega_ints(stream: io.BytesIO, encoding_type: str) -> list[int]:
    """Read a length-prefixed omega-encoded integer array from a stream."""
    num_bytes = int.from_bytes(stream.read(4), "little")
    raw = stream.read(num_bytes)
    bits = bitarray()
    bits.frombytes(raw)
    return OmegaEncoder().decode(bits, encoding_type)


def _decode_polygon_blob(data: bytes) -> _PolygonStore:
    """Decode ``encoded_polygons.bin`` payload (after brotli) into a polygon store."""
    stream = io.BytesIO(data)
    tile_size = int.from_bytes(stream.read(4), "little")
    stream.read(4)  # num_rows (unused)
    stream.read(4)  # num_cols (unused)

    polygon_lengths_nbytes = int.from_bytes(stream.read(4), "little")
    polygon_lengths = array.array("I")
    polygon_lengths.frombytes(stream.read(polygon_lengths_nbytes))

    x_jumps = _read_omega_ints(stream, "integers")
    y_jumps = _read_omega_ints(stream, "integers")
    num_points_in_tile = _read_omega_ints(stream, "naturalOnly")

    # Clamp to shortest array -- omega padding can produce trailing values
    num_jumps = min(len(x_jumps), len(y_jumps))
    x_jumps = x_jumps[:num_jumps]
    y_jumps = y_jumps[:num_jumps]
    num_segments = min(num_jumps, len(num_points_in_tile))
    num_points_in_tile = num_points_in_tile[:num_segments]
    x_jumps = x_jumps[:num_segments]
    y_jumps = y_jumps[:num_segments]

    remainders_nbytes = int.from_bytes(stream.read(4), "little")
    remainders = list(stream.read(remainders_nbytes))

    # Reconstruct flat coordinate list from tile jumps + remainders
    tile_x = 0
    tile_y = 0
    remainder_idx = 0
    flat: list[int] = []

    for num_points, dx, dy in zip(
        num_points_in_tile, x_jumps, y_jumps, strict=True
    ):
        if remainder_idx >= len(remainders):
            break
        tile_x += dx
        tile_y += dy
        points_left = (len(remainders) - remainder_idx) // 2
        num_to_take = min(num_points, points_left)
        for _ in range(num_to_take):
            remainder_x = remainders[remainder_idx]
            remainder_y = remainders[remainder_idx + 1]
            remainder_idx += 2
            flat.append(tile_x * tile_size + remainder_x)
            flat.append(tile_y * tile_size + remainder_y)

    # Split flat coords into individual polygons using polygon_lengths
    polygons = _PolygonStore()
    offset = 0
    for length in polygon_lengths:
        chunk = flat[offset : offset + int(length)]
        offset += int(length)
        if chunk:
            polygons.add_polygon(chunk)
    return polygons


def _decode_mask_png(png_buf: bytes) -> tuple[int, list[tuple[int, int]]]:
    """Decode a 1-bit mask PNG into (tile_size, [(x, y), ...])."""
    reader = png.Reader(bytes=png_buf)
    width, _height, rows, info = reader.read()
    points = []
    if info["bitdepth"] == 1:
        for row_i, row in enumerate(rows):
            for x, b in enumerate(row):
                if b != 0:
                    points.append((x, row_i))
    return width, points


def _decode_heatmap_png(png_buf: bytes) -> tuple[int, int, list[list[int]]]:
    """Decode a greyscale PNG into (width, height, matrix)."""
    reader = png.Reader(bytes=png_buf)
    width, height, rows, _info = reader.read()
    matrix = [list(row) for row in rows]
    return width, height, matrix


# ---------------------------------------------------------------------------
# Decoder class
# ---------------------------------------------------------------------------


class Decoder:
    """Decode an Anno2 ZIP archive into a point / polygon / heatmap store."""

    def __init__(self, anno2: zipfile.ZipFile) -> None:
        self.anno2 = anno2
        self.system_metadata: dict = {}
        self.anno2_type: str = ""
        self.items: Anno2Items | None = None
        self._read_system_metadata()

    def _read_system_metadata(self) -> None:
        try:
            raw = self.anno2.read("system_metadata.json")
        except KeyError as exc:
            raise ValueError("Anno2 ZIP missing system_metadata.json") from exc

        self.system_metadata = json.loads(raw)
        ver_str = self.system_metadata["version"]
        v = version.parse(ver_str)
        if v >= version.parse("1.0.0"):
            raise ValueError(f"Anno2 version {ver_str} must be below 1.0.0")
        if v != version.parse("0.2.0"):
            _logger.warning("Anno2 version %s is not 0.2.0, assuming compatible", ver_str)

        self.anno2_type = self.system_metadata["type"]
        if self.anno2_type not in _SUPPORTED_TYPES:
            raise ValueError(
                f"Anno2 type '{self.anno2_type}' not in {_SUPPORTED_TYPES}"
            )

    def decode(self) -> None:
        """Decode the archive into ``self.items``."""
        if self.anno2_type == "polygons":
            self.items = self._decode_polygons()
        elif self.anno2_type in ("points", "mask"):
            self.items = self._decode_points()
        elif self.anno2_type in ("heatmap", "binary-heatmap"):
            self.items = self._decode_heatmap()
        else:
            raise TypeError(f"Unrecognised anno2 type: {self.anno2_type!r}")

        expected = self.system_metadata.get("numItems")
        if isinstance(expected, int) and expected != len(self.items):
            _logger.warning(
                "Item count mismatch: expected %d, got %d", expected, len(self.items)
            )

    # -- Type-specific decoders ---------------------------------------------

    def _decode_polygons(self) -> _PolygonStore:
        # Prefer full-fidelity, fall back to simplified
        polygons: _PolygonStore | None = None
        for member in (
            "polygon_container/encoded_polygons.bin.br",
            "polygon_container/simpl_encoded_polygons.bin.br",
        ):
            if member in self.anno2.namelist():
                raw = brotli.decompress(self.anno2.read(member))
                polygons = _decode_polygon_blob(raw)
                break
        if polygons is None:
            raise ValueError("Anno2 polygon ZIP contains no encoded_polygons member")

        # Restore negative polygon associations (holes)
        if "polygon_container/negative_polygons.json" in self.anno2.namelist():
            neg_data = json.loads(
                self.anno2.read("polygon_container/negative_polygons.json")
            )
            for pos_i_str, neg_indices in neg_data.items():
                pos_i = int(pos_i_str)
                for neg_i in neg_indices:
                    polygons.link_negative(pos_i, int(neg_i))

        # Restore labels
        if "labels.json" in self.anno2.namelist():
            polygons.labels = json.loads(self.anno2.read("labels.json"))

        # Restore per-item metadata
        if "items_metadata.json.br" in self.anno2.namelist():
            raw_meta = json.loads(
                brotli.decompress(self.anno2.read("items_metadata.json.br"))
            )
            if isinstance(raw_meta, dict):
                for idx_str, meta in raw_meta.items():
                    polygons.metadata[int(idx_str)] = meta

        if "polygon_container/shape_overlay.json" in self.anno2.namelist():
            overlay_raw = json.loads(
                self.anno2.read("polygon_container/shape_overlay.json")
            )
            if isinstance(overlay_raw, list):
                for entry in overlay_raw:
                    if not isinstance(entry, dict):
                        continue
                    polygon_i = entry.get("polygon_i")
                    if polygon_i is None:
                        continue
                    spec = {
                        k: v
                        for k, v in entry.items()
                        if k != "polygon_i"
                    }
                    polygons.shape_overlay[int(polygon_i)] = spec

        return polygons

    def _decode_points(self) -> _PointStore:
        points = _PointStore()
        if "anno1_points.json.br" in self.anno2.namelist():
            data = json.loads(brotli.decompress(self.anno2.read("anno1_points.json.br")))
            for pt in data:
                points.add_point(int(pt["x"]), int(pt["y"]))
            return points

        # Dense mask tiles
        if "masks.tar.gz" not in self.anno2.namelist():
            raise ValueError(
                "Anno2 points ZIP contains neither anno1_points.json.br nor masks.tar.gz"
            )
        with self.anno2.open("masks.tar.gz") as f:
            with tarfile.open(fileobj=f, mode="r:gz") as tar:
                for member in tar.getmembers():
                    if not member.isfile() or not member.name.startswith("tile_"):
                        continue
                    extracted = tar.extractfile(member)
                    assert extracted is not None  # guaranteed by member.isfile() check
                    content = extracted.read()
                    if content[:4] != b"\x89PNG":
                        continue
                    parts = member.name.split("_")
                    tile_x = int(parts[1][1:])
                    tile_y = int(parts[2][1:].removesuffix(".png"))
                    tile_size, tile_points = _decode_mask_png(content)
                    for x, y in tile_points:
                        points.add_point(tile_x * tile_size + x, tile_y * tile_size + y)
        return points

    def _decode_heatmap(self) -> _HeatmapStore:
        meta = json.loads(self.anno2.read("heatmap_metadata.json"))
        x_offset = meta["x"]
        y_offset = meta["y"]
        size_per_pixel = meta["sizePerPixel"]

        _, _, matrix = _decode_heatmap_png(self.anno2.read("heatmap.png"))
        return _HeatmapStore(
            matrix, x_offset, y_offset, size_per_pixel, name=self.anno2_type
        )

    def dump_user_metadata_to_file(self, path: str) -> None:
        """Write user_metadata.json to disk."""
        with open(path, "wb") as file:
            file.write(self.anno2.read("user_metadata.json"))
