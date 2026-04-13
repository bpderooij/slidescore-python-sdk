import array

from ._polygon_codec import polygons_to_bytes
from ._stores import TileRange, _PolygonStore


class PolygonContainer:
    """Spatial index of polygons binned into tiles.

    Each polygon index is stored in every tile whose bounding box it
    intersects.  "Big" polygons are additionally tracked separately.
    """

    def __init__(self, tile_size: int, polygons: _PolygonStore):
        self.all_tiles: dict = {}
        self.big_tiles: dict = {}
        self.polygons = polygons
        self.tile_size = tile_size

    def store_polygon_i(
        self, polygon_i: int, tile_range: TileRange, is_big: bool
    ) -> None:
        """Register *polygon_i* in all tiles covered by *tile_range*."""
        for tile_y in range(tile_range.y_start, tile_range.y_end + 1):
            for tile_x in range(tile_range.x_start, tile_range.x_end + 1):
                if tile_y not in self.all_tiles:
                    self.all_tiles[tile_y] = {}
                if tile_x not in self.all_tiles[tile_y]:
                    self.all_tiles[tile_y][tile_x] = array.array("I")

                if is_big and tile_y not in self.big_tiles:
                    self.big_tiles[tile_y] = {}
                if is_big and tile_x not in self.big_tiles[tile_y]:
                    self.big_tiles[tile_y][tile_x] = array.array("I")

                self.all_tiles[tile_y][tile_x].append(polygon_i)
                if is_big:
                    self.big_tiles[tile_y][tile_x].append(polygon_i)

    def encode_polygons(self) -> bytes:
        """Encode stored polygons into a space-efficient binary format."""
        return polygons_to_bytes(self.polygons.polygons)

    def encode_simplified_polygons(self) -> bytes:
        """Encode simplified polygon copies into a space-efficient binary format."""
        return polygons_to_bytes(self.polygons.simplified_polygons)
