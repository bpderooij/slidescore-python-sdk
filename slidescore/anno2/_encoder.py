import copy
import io
import json
import logging
import math
import tarfile
import zipfile
from collections.abc import Iterable
from typing import cast

import brotli
import msgpack

from .containers import Heatmap, Item, Items, Points, Polygon, Polygons, TileRange
from ._image_utils import encode_png, _points_to_png, lookup_table_to_png
from ._polygon_container import PolygonContainer
from ._serializers import msgpack_encoder

_logger = logging.getLogger(__name__)

# Default heuristics: single numbers here, mirrored on ``Encoder`` as class
# attributes so callers can patch ``_encoder._FEW_POINTS_JSON_CUTOFF`` (etc.)
# or ``Encoder.few_points_json_cutoff``. Reassigning a module constant after
# ``Encoder`` is defined does not change existing class attributes; set the
# class attribute, or patch constants before import / define a subclass.
DEFAULT_BIG_POLYGON_SIZE_CUTOFF = 10_000
_FEW_POINTS_JSON_CUTOFF = 500_000
_LOW_DENSITY_POINTS_PER_TILE = 30
_LOOKUP_TABLE_TILE_SIZES: tuple[int, ...] = (32, 256)
_POLYGON_LOOKUP_WEIGHT = 15


def _bounding_box(
    vertices: list[tuple[float, float]],
) -> tuple[float, float, float, float]:
    min_x = min(vertex[0] for vertex in vertices)
    min_y = min(vertex[1] for vertex in vertices)
    max_x = max(vertex[0] for vertex in vertices)
    max_y = max(vertex[1] for vertex in vertices)
    return min_x, min_y, max_x, max_y


def _bounding_box_area(
    min_x: float, min_y: float, max_x: float, max_y: float
) -> float:
    return (max_x - min_x) * (max_y - min_y)


def _tile_range_for_bounds(
    min_x: float, min_y: float, max_x: float, max_y: float, tile_size: int
) -> TileRange:
    return TileRange(
        x_start=math.floor(min_x / tile_size),
        y_start=math.floor(min_y / tile_size),
        x_end=math.floor(max_x / tile_size),
        y_end=math.floor(max_y / tile_size),
    )


def _points_anno1_json(point_coordinates: Iterable[tuple[int, int]]) -> str:
    return json.dumps([{"x": cx, "y": cy} for cx, cy in point_coordinates])


def _add_to_tar(tar: tarfile.TarFile, buffer: bytes, name: str) -> None:
    info = tarfile.TarInfo(name=name)
    info.size = len(buffer)
    tar.addfile(info, io.BytesIO(buffer))


def _add_polygon_container(
    zf: zipfile.ZipFile, container: PolygonContainer, dir_name: str
) -> None:
    tile_polygons_i_bytes = msgpack.dumps(
        container.all_tiles, default=msgpack_encoder
    )
    zf.writestr(
        f"{dir_name}/tile_polygons_i.msgpack.br",
        brotli.compress(tile_polygons_i_bytes, quality=8),
    )

    big_tile_polygons_i_bytes = msgpack.dumps(
        container.big_tiles, default=msgpack_encoder
    )
    zf.writestr(
        f"{dir_name}/big_tile_polygons_i.msgpack.br",
        brotli.compress(big_tile_polygons_i_bytes, quality=8),
    )

    zf.writestr(
        f"{dir_name}/encoded_polygons.bin.br",
        brotli.compress(container.encode_polygons(), quality=8),
    )
    zf.writestr(
        f"{dir_name}/simpl_encoded_polygons.bin.br",
        brotli.compress(container.encode_simplified_polygons(), quality=8),
    )
    zf.writestr(
        f"{dir_name}/negative_polygons.json",
        json.dumps(container.polygons.negative_polygons_i, indent=2).encode(),
    )


class Encoder:
    """Encode Points, Polygons, or Heatmap into an Anno2 ZIP archive.

    Orchestrates tiling, lookup tables, and ZIP layout. Pure geometry,
    wire-format helpers, and zip/tar serialization live at module level
    (e.g. ``_bounding_box``, ``_add_polygon_container``).

    Parameters
    ----------
    items
        Points, polygons, or heatmap to encode.
    big_polygon_size_cutoff
        Axis-aligned bounding-box area above which a polygon is stored as
        "big" in the tile index.
    """

    few_points_json_cutoff: int = _FEW_POINTS_JSON_CUTOFF
    low_density_points_per_tile: int = _LOW_DENSITY_POINTS_PER_TILE
    lookup_table_tile_sizes: tuple[int, ...] = _LOOKUP_TABLE_TILE_SIZES
    polygon_lookup_weight: int = _POLYGON_LOOKUP_WEIGHT

    def __init__(
        self,
        items: Items,
        big_polygon_size_cutoff: int = DEFAULT_BIG_POLYGON_SIZE_CUTOFF,
    ) -> None:
        self.items = items
        self.big_polygon_size_cutoff = big_polygon_size_cutoff
        self._data_items: dict = {"numItems": len(items)}
        self._data_lookups: list = []

        type_string = items.name.lower()
        self.system_metadata = {
            "version": "0.2.0",
            "type": type_string,
            "numItems": len(items),
        }
        self.user_metadata: dict = {}

        if isinstance(items, Points):
            _logger.debug(
                "Loaded %s points in encoder, type: %s",
                self._data_items["numItems"],
                type_string,
            )
        elif isinstance(items, Polygons):
            self.items = copy.deepcopy(items)
            num_points = len(self.items.polygons.values_array) // 2
            _logger.debug(
                "Loaded %s polygons in encoder, with num points %s",
                self._data_items["numItems"],
                num_points,
            )
            self.items.simplify()
            num_points = len(self.items.polygons.values_array) // 2
            _logger.debug("Simplified to num points %s", num_points)
        elif isinstance(items, Heatmap):
            _logger.debug(
                "Loaded %s byte %s in encoder, with shape %s %s",
                self._data_items["numItems"],
                items.name,
                len(items.matrix),
                len(items.matrix[0]),
            )

    def _item_bounding_box(self, item: Item) -> tuple[float, float, float, float]:
        """Return (min_x, min_y, max_x, max_y) for a point or polygon item."""
        if isinstance(self.items, Points):
            x, y = cast(tuple[int, int], item)
            return _bounding_box([(float(x), float(y))])
        polygon_item = cast(Polygon, item)
        return _bounding_box(polygon_item["positiveVertices"])

    def _polygon_bbox_area(self, item: Item) -> float:
        return _bounding_box_area(*self._item_bounding_box(item))

    def generate_tile_data(self, tile_size: int = 256) -> None:
        """Bin items into tiles and store the result in ``_data_items``."""
        if isinstance(self.items, Points):
            self._data_items["masks"] = self._bin_points_into_tiles(tile_size)
        elif isinstance(self.items, Polygons):
            self._data_items["polygonContainer"] = self._bin_polygons_into_tiles(tile_size)
        elif isinstance(self.items, Heatmap):
            height, width = len(self.items.matrix), len(self.items.matrix[0])
            self._data_items["heatmapPng"] = encode_png(
                self.items.matrix, width, height, bitdepth=8
            )

    def _bin_points_into_tiles(self, tile_size: int):
        items = cast(Points, self.items)

        if len(items) < self.few_points_json_cutoff and items.name == "points":
            _logger.info(
                "Anno2 points layer: count %s < few_points_json_cutoff (%s) — "
                "using anno1 JSON (anno1_points.json.br), not tiled mask PNGs; "
                "SlideScore still shows these as normal point annotations.",
                len(items),
                self.few_points_json_cutoff,
            )
            return _points_anno1_json(items)

        tile_bins: dict = {}
        num_tiles = 0
        for point in items:
            img_x, img_y = point
            tile_x = math.floor(img_x / tile_size)
            tile_y = math.floor(img_y / tile_size)

            if tile_y not in tile_bins:
                tile_bins[tile_y] = {}
            if tile_x not in tile_bins[tile_y]:
                tile_bins[tile_y][tile_x] = []
                num_tiles += 1

            tile_bins[tile_y][tile_x].extend((img_x % tile_size, img_y % tile_size))

        num_points_per_tile = len(items) / num_tiles
        if num_points_per_tile < self.low_density_points_per_tile and items.name == "points":
            _logger.info(
                "Anno2 points layer: mean %.1f points/tile < low_density_points_per_tile "
                "(%s) — using anno1 JSON (anno1_points.json.br), not tiled mask PNGs; "
                "SlideScore still shows these as normal point annotations.",
                num_points_per_tile,
                self.low_density_points_per_tile,
            )
            return _points_anno1_json(items)

        _logger.debug(
            "Compressing tiles as PNGs: %s tiles, %s points, %.1f pts/tile",
            num_tiles,
            len(items),
            len(items) / num_tiles,
        )
        for tile_y in tile_bins:
            for tile_x in tile_bins[tile_y]:
                tile_bins[tile_y][tile_x] = _points_to_png(
                    tile_bins[tile_y][tile_x], tile_size
                )
        _logger.debug("Done compressing tiles")
        return tile_bins

    def _bin_polygons_into_tiles(self, tile_size: int) -> PolygonContainer:
        items = self.items
        tile_bins = PolygonContainer(tile_size, items)

        for i, polygon in enumerate(items):
            is_big = (
                self._polygon_bbox_area(polygon) > self.big_polygon_size_cutoff
            )
            tile_indices = _tile_range_for_bounds(
                *self._item_bounding_box(polygon), tile_size
            )
            tile_bins.store_polygon_i(i, tile_indices, is_big)

        return tile_bins

    def populate_lookup_tables(self) -> None:
        """Build density-map PNGs and store them in ``_data_lookups``."""
        if isinstance(self.items, Heatmap):
            _logger.debug("Skipping lookup table generation for heatmap")
            return

        if (
            len(self.items) < self.few_points_json_cutoff
            and self.items.name == "points"
        ):
            _logger.debug(
                "Skipping density lookup PNGs: points count %s < few_points_json_cutoff "
                "(%s) with name=points (anno1 JSON layer has no mask.tar.gz to index).",
                len(self.items),
                self.few_points_json_cutoff,
            )
            return

        for tile_size in self.lookup_table_tile_sizes:
            fast_path = next(
                (
                    d
                    for d in self._data_lookups
                    if tile_size % d["tile_size"] == 0
                ),
                None,
            )

            if fast_path:
                lookup_table = self._bin_lookup_fast(
                    tile_size, fast_path["tile_size"], fast_path["lookup"]
                )
            else:
                lookup_table = self._bin_lookup(tile_size)

            lookup_table["png"] = lookup_table_to_png(lookup_table)
            self._data_lookups.append(lookup_table)
            _logger.debug("Done with lookup table of size %s", tile_size)

    def _bin_lookup(self, tile_size: int) -> dict:
        items = self.items
        num_points_to_add = (
            1 if isinstance(items, Points) else self.polygon_lookup_weight
        )

        tile_bins: dict = {}
        data = {"tile_size": tile_size, "lookup": tile_bins, "maxValue": 0}

        for item in items:
            if isinstance(items, Polygons):
                if self._polygon_bbox_area(item) > self.big_polygon_size_cutoff:
                    continue

            tile_indices = _tile_range_for_bounds(
                *self._item_bounding_box(item), tile_size
            )
            for y in range(tile_indices.y_start, tile_indices.y_end + 1):
                for x in range(tile_indices.x_start, tile_indices.x_end + 1):
                    if y not in tile_bins:
                        tile_bins[y] = {}
                    if x not in tile_bins[y]:
                        tile_bins[y][x] = 0
                    tile_bins[y][x] += num_points_to_add
                    data["maxValue"] = max(data["maxValue"], tile_bins[y][x])

        return data

    def _bin_lookup_fast(
        self, new_tile_size: int, old_tile_size: int, old_lookup: dict
    ) -> dict:
        """Derive a coarser lookup table by summing a finer one."""
        if new_tile_size % old_tile_size != 0:
            raise ValueError("Cannot use fast path: tile sizes are not multiples")

        ratio = new_tile_size / old_tile_size
        tile_bins: dict = {}
        data = {"tile_size": new_tile_size, "lookup": tile_bins, "maxValue": 0}

        for y, row in old_lookup.items():
            for x, count in row.items():
                new_y = math.floor(y / ratio)
                new_x = math.floor(x / ratio)
                if new_y not in tile_bins:
                    tile_bins[new_y] = {}
                if new_x not in tile_bins[new_y]:
                    tile_bins[new_y][new_x] = 0
                tile_bins[new_y][new_x] += count
                data["maxValue"] = max(tile_bins[new_y][new_x], data["maxValue"])

        return data

    def dump_to_file(self, path: str) -> None:
        """Encode and write all data to an Anno2 ZIP file at *path*."""
        _logger.debug("Encoding and dumping to zipfile")

        if not path.endswith(".zip"):
            path += ".zip"

        with zipfile.ZipFile(path, mode="w", compression=zipfile.ZIP_STORED) as zf:
            zf.writestr(
                "system_metadata.json",
                json.dumps(self.system_metadata, indent=2).encode(),
            )
            zf.writestr(
                "user_metadata.json",
                json.dumps(self.user_metadata, indent=2).encode(),
            )

            for lookup_data in self._data_lookups:
                zf.writestr(
                    f"lookup-tables/density_{lookup_data['tile_size']}px.png",
                    lookup_data["png"],
                )

            if "masks" in self._data_items:
                if isinstance(self._data_items["masks"], dict):
                    tar_gz_fh = io.BytesIO()
                    with tarfile.open(fileobj=tar_gz_fh, mode="w:gz") as tar:
                        for tile_y, row in self._data_items["masks"].items():
                            for tile_x, tile_png_bytes in row.items():
                                _add_to_tar(
                                    tar,
                                    tile_png_bytes,
                                    f"tile_x{tile_x}_y{tile_y}.png",
                                )

                    zf.writestr("masks.tar.gz", tar_gz_fh.getbuffer())
                else:
                    zf.writestr(
                        "anno1_points.json.br",
                        brotli.compress(self._data_items["masks"].encode(), quality=8),
                    )

            has_metadata = len(getattr(self.items, "metadata", []))
            if has_metadata:
                zf.writestr(
                    "items_metadata.json.br",
                    brotli.compress(
                        json.dumps(self.items.metadata).encode(), quality=8
                    ),
                )

            if "polygonContainer" in self._data_items:
                _add_polygon_container(
                    zf, self._data_items["polygonContainer"], "polygon_container"
                )

            if isinstance(self.items, Polygons) and len(self.items.labels) > 0:
                zf.writestr(
                    "labels.json",
                    json.dumps(self.items.labels, indent=2).encode(),
                )

            if "heatmapPng" in self._data_items:
                zf.writestr("heatmap.png", self._data_items["heatmapPng"])
                zf.writestr(
                    "heatmap_metadata.json",
                    json.dumps(self.items.get_metadata(), indent=2).encode(),
                )

    def add_metadata(self, metadata: dict) -> None:
        """Set user metadata to include in the output ZIP."""
        self.user_metadata = metadata
