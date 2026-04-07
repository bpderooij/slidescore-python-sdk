import array
import logging

from .AnnoClasses import EfficientArray
from .PolygonContainer import PolygonContainer

# Backward-compatible re-exports — parsers have moved to slidescore/parsers/
from ..parsers.geojson import extract_geojson, read_geo_json
from ..parsers.heatmap_tsv import read_tsv_binary_heatmap, read_tsv_heatmap
from ..parsers.slidescore_json import read_slidescore_json
from ..parsers.tsv import read_tsv, read_tsv_points, read_tsv_polygons

_logger = logging.getLogger(__name__)

# Export functions
supported_types = {"B": "uint8", "H": "uint16", "I": "uint32"}


def encode_typed_arr(obj):
    """Encodes a array.array into a bytebuffer and container object"""
    if len(obj) == 0:
        return []
    if obj.typecode not in supported_types:
        raise Exception("Unsupported typed array")

    array_type = supported_types[obj.typecode]

    typed_array_obj = {
        "isTypedArray": True,
        "bytes": obj.tobytes(),
        "type": array_type,
        "len": len(obj),
    }
    return typed_array_obj


def encode_effecient_arr(obj: EfficientArray):
    """Encodes an EfficientArray into a container object with a destructered representation"""
    return {
        "isEfficientArray": True,
        "data": {
            "offsetArray": obj.offsetArray,
            "valuesArray": obj.valuesArray,
            "length": len(obj),
        },
    }


def encode_polygon_container(obj: PolygonContainer):
    """Encodes a polygon container into a space effecient polygons buffer and the tile and negative polygons information"""
    return {
        "isPolygonContainer": True,
        "data": {
            "allTiles": obj.allTiles,
            "polygons": obj.encode_polygons(),
            "negativePolygons": obj.polygons.negative_polygons_i,
            "tileSize": obj.tile_size,
        },
    }


def msgpack_encoder(obj):
    """Encoder that calls encode_polygon_container & encode_typed_arr for their respective objects"""
    if isinstance(obj, PolygonContainer):
        return encode_polygon_container(obj)

    if isinstance(obj, array.array):
        return encode_typed_arr(obj)


def get_logger(verbosity: int = 0) -> logging.Logger:
    """Configure root logging (when unconfigured) and return the utils logger.

    Uses :func:`logging.basicConfig`, which has no effect if the root logger
    already has handlers.
    """
    level = logging.DEBUG if verbosity >= 2 else logging.INFO
    logging.basicConfig(
        level=level,
        format="%(asctime)s [%(levelname)s] %(message)s",
        datefmt="%H:%M:%S",
    )
    logger = logging.getLogger(__name__)
    logger.setLevel(level)
    return logger
