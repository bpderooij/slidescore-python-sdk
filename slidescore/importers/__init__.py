"""Format importers targeting :class:`slidescore.geometries` types.

The public entry points are the ``Annotations.from_*`` classmethods in
:mod:`slidescore.annotations`; the functions here are the underlying
parsers and are re-exported for direct use when needed.
"""

from .geojson import parse_geojson
from .slidescore import (
    parse_heatmap_tsv,
    parse_points_tsv,
    parse_polygons_tsv,
    parse_slidescore_json,
    read_slidescore_json,
)

__all__ = [
    "parse_geojson",
    "parse_heatmap_tsv",
    "parse_points_tsv",
    "parse_polygons_tsv",
    "parse_slidescore_json",
    "read_slidescore_json",
]
