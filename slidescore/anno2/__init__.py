"""Anno2 codec -- encode and decode SlideScore Anno2 ZIP archives.

This is the primary value of the slidescore SDK: the anno2 binary format
(omega encoding, tiled polygon containers, density maps) is complex,
undocumented, and only this SDK implements it.

Usage::

    from slidescore.anno2 import encode, decode, Points, Polygons, Heatmap
"""

from __future__ import annotations

import zipfile
from pathlib import Path
from typing import TYPE_CHECKING

from .containers import Heatmap, Points, Polygons
from ._encoder import Encoder
from ._decoder import Decoder, items_to_anno1, items_to_geojson, write_items_tsv, write_items_png

if TYPE_CHECKING:
    from .containers import Items


def encode(
    items: Items,
    output_path: str | Path,
    *,
    metadata: dict | None = None,
    tile_size: int = 256,
    big_polygon_size_cutoff: int = 100 * 100,
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
    """
    encoder = Encoder(items, big_polygon_size_cutoff=big_polygon_size_cutoff)
    encoder.generate_tile_data(tile_size)
    encoder.populate_lookup_tables()
    if metadata:
        encoder.add_metadata(metadata)
    encoder.dump_to_file(str(output_path))


def decode(anno2_path: str | Path) -> Points | Polygons | Heatmap:
    """Decode an Anno2 ZIP file into annotation items.

    Parameters
    ----------
    anno2_path
        Path to the Anno2 ZIP file.

    Returns
    -------
    Points | Polygons | Heatmap
        The decoded annotation items.
    """
    with zipfile.ZipFile(str(anno2_path)) as zf:
        decoder = Decoder(zf)
        decoder.decode()
        return decoder.items


__all__ = [
    "encode",
    "decode",
    "Encoder",
    "Decoder",
    "Points",
    "Polygons",
    "Heatmap",
    "items_to_anno1",
    "items_to_geojson",
    "write_items_tsv",
    "write_items_png",
]
