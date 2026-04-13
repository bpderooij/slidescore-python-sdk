import array

from ._stores import EfficientArray
from ._polygon_container import PolygonContainer

_SUPPORTED_TYPECODES: dict[str, str] = {"B": "uint8", "H": "uint16", "I": "uint32"}


def encode_typed_arr(obj: array.array) -> list | dict:
    """Encode an ``array.array`` into a msgpack-friendly container."""
    if len(obj) == 0:
        return []
    if obj.typecode not in _SUPPORTED_TYPECODES:
        raise ValueError(f"Unsupported array typecode: {obj.typecode!r}")

    return {
        "isTypedArray": True,
        "bytes": obj.tobytes(),
        "type": _SUPPORTED_TYPECODES[obj.typecode],
        "len": len(obj),
    }


def encode_efficient_array(obj: EfficientArray) -> dict:
    """Encode an ``EfficientArray`` into a msgpack-friendly container."""
    return {
        "isEfficientArray": True,
        "data": {
            "offsetArray": obj.offset_array,
            "valuesArray": obj.values_array,
            "length": len(obj),
        },
    }


def encode_polygon_container(obj: PolygonContainer) -> dict:
    """Encode a ``PolygonContainer`` into a msgpack-friendly container."""
    return {
        "isPolygonContainer": True,
        "data": {
            "allTiles": obj.all_tiles,
            "polygons": obj.encode_polygons(),
            "negativePolygons": obj.polygons.negative_polygons_i,
            "tileSize": obj.tile_size,
        },
    }


def msgpack_encoder(obj):
    """Custom msgpack encoder for PolygonContainer and array.array objects."""
    if isinstance(obj, PolygonContainer):
        return encode_polygon_container(obj)
    if isinstance(obj, array.array):
        return encode_typed_arr(obj)
