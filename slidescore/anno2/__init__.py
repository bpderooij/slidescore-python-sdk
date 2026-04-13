"""Anno2 codec -- encode and decode SlideScore Anno2 ZIP archives.

This is the primary value of the slidescore SDK: the anno2 binary format
(omega encoding, tiled polygon containers, density maps) is complex,
undocumented, and only this SDK implements it.

Usage::

    from slidescore.anno2 import encode, decode
"""

from __future__ import annotations

import zipfile
from pathlib import Path

from slidescore.types import Anno2Items

from ._decoder import Decoder
from ._encoder import DEFAULT_BIG_POLYGON_SIZE_CUTOFF, Encoder
from ._stores import _HeatmapStore, _PointStore, _PolygonStore


def encode(
    items: Anno2Items,
    output_path: str | Path,
    *,
    metadata: dict | None = None,
    tile_size: int = 256,
    big_polygon_size_cutoff: int = DEFAULT_BIG_POLYGON_SIZE_CUTOFF,
) -> None:
    """Encode annotation items to an Anno2 ZIP file.

    Parameters
    ----------
    items
        A ``Points``, ``Polygons``, or ``Heatmap`` instance.
    output_path
        Destination path for the ZIP file.
    metadata
        Optional user metadata dict to include in the archive.
    tile_size
        Tile size for spatial binning (default 256).
    big_polygon_size_cutoff
        Bounding-box area threshold for "big" polygon classification.
        Default is :data:`DEFAULT_BIG_POLYGON_SIZE_CUTOFF`.
    """
    encoder = Encoder(items, big_polygon_size_cutoff=big_polygon_size_cutoff)
    encoder.generate_tile_data(tile_size)
    encoder.populate_lookup_tables()
    if metadata:
        encoder.add_metadata(metadata)
    encoder.dump_to_file(str(output_path))


def decode(anno2_path: str | Path) -> _PointStore | _PolygonStore | _HeatmapStore:
    """Decode an Anno2 ZIP file into a codec storage primitive.

    Parameters
    ----------
    anno2_path
        Path to the Anno2 ZIP file.

    Returns
    -------
    _PointStore | _PolygonStore | _HeatmapStore
        The decoded storage primitive. Use the ``Annotations`` collection
        for a domain-model view; this return type is an implementation detail of the codec.
    """
    with zipfile.ZipFile(str(anno2_path)) as zf:
        decoder = Decoder(zf)
        decoder.decode()
        assert decoder.items is not None
        return decoder.items


__all__ = [
    "encode",
    "decode",
    "DEFAULT_BIG_POLYGON_SIZE_CUTOFF",
    "Encoder",
    "Decoder",
]
