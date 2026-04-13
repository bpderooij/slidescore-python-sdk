import argparse
import gzip
import json
import logging

from slidescore.anno2._encoder import Encoder
from slidescore.importers.geojson import from_geojson
from slidescore.importers.slidescore import (
    from_heatmap_tsv,
    from_points_tsv,
    from_polygons_tsv,
    read_slidescore_json,
)
from slidescore.shapes import (
    EllipseRecord,
    PointRecord,
    PolygonRecord,
    RectangleRecord,
    to_containers,
)

DESC = """
This program converts a items TSV file (or slidescore_anno1.json) of either points in a mask, polygons or a heatmap, into a binned format for fast lookup.
Author: Bart.
"""

_logger = logging.getLogger(__name__)


def _load_geojson_items(path: str):
    with open(path) as fh:
        data = json.load(fh)
    records = from_geojson(data)
    points = [
        record for record in records if isinstance(record, PointRecord)
    ]
    polys = [
        record
        for record in records
        if isinstance(
            record,
            (PolygonRecord, EllipseRecord, RectangleRecord),
        )
    ]
    if points and polys:
        _logger.warning(
            "Detected BOTH points and polygons in GeoJSON, only continuing with polygons"
        )
        _logger.warning(
            "Please remove the points from the GeoJSON to prevent ambiguity"
        )
        records = polys
    return to_containers(records)


def _load_tsv_items(path: str, points_type: str, experimental: bool):
    with open(path) as fh:
        text = fh.read()
    first_line = text.split("\n", 1)[0]
    line_parts = first_line.split()

    is_heatmap = len(line_parts) >= 1 and line_parts[0].lower() == "heatmap"
    is_binary = len(line_parts) >= 1 and line_parts[0].lower() == "binary-heatmap"
    if is_binary and not experimental:
        raise ValueError(
            "Wanted to encode a binary heatmap but --experimental is not present"
        )

    if is_heatmap or is_binary:
        return to_containers(from_heatmap_tsv(text))

    are_points = len(line_parts) == 2
    if are_points:
        items = to_containers(from_points_tsv(text))
        if points_type == "mask":
            items.name = "mask"
        return items
    return to_containers(from_polygons_tsv(text))


def load_tsv_items(path: str, points_type: str, *, experimental: bool = False):
    """Load points, polygons, or heatmap items from a TSV path (CLI-compatible)."""
    return _load_tsv_items(path, points_type, experimental)


def main(argv=None):
    parser = argparse.ArgumentParser(description=DESC)
    parser.add_argument(
        "--items-path",
        "-i",
        type=str,
        required=True,
        help="Input file path, should be a TSV / GeoJSON / SlideScore JSON file",
    )
    parser.add_argument(
        "--output",
        "-o",
        type=str,
        default="./items_binned.zip",
        help="Output path of the binned items file",
    )
    parser.add_argument(
        "--metadata",
        "-m",
        type=str,
        help="Path of JSON file containing user-specified metadata about the input file, will be encoded in the output file",
    )
    parser.add_argument(
        "--points-type",
        "-pt",
        choices=["mask", "circles"],
        default="circles",
        help="Type of points that are provided in the TSV, either single pixels (mask), or center points of circles (default)",
    )
    parser.add_argument(
        "--experimental",
        action="store_true",
        default=False,
        help="Enable experimental support for anno2 formats not universally supported",
    )

    # Parse the arguments
    args = parser.parse_args(argv)
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
        datefmt="%H:%M:%S",
    )
    logger = logging.getLogger(__name__)
    raw_items_path = args.items_path
    binned_items_path: str = args.output

    logger.info("Reading data into memory")

    if raw_items_path.endswith(".tsv"):
        items = _load_tsv_items(raw_items_path, args.points_type, args.experimental)
    elif raw_items_path.endswith(".geojson"):
        items = _load_geojson_items(raw_items_path)
    elif raw_items_path.endswith(".json"):
        with open(raw_items_path) as fh:
            data = json.load(fh)
            items = read_slidescore_json(data)
    elif raw_items_path.endswith(".json.gz"):
        with gzip.open(raw_items_path, "r") as fh:
            data = json.load(fh)
            items = read_slidescore_json(data)
    else:
        raise ValueError("Please provide a .tsv/.geojson/.json file")

    logger.info("Loaded data into memory")

    encoder = Encoder(items, big_polygon_size_cutoff=100 * 100)
    encoder.generate_tile_data(256)
    logger.info("Binned items into 256x256 tiles")

    encoder.populate_lookup_tables()
    logger.info("Generated lookup tables")
    if args.metadata:
        with open(args.metadata) as fh:
            metadata = json.load(fh)
            encoder.add_metadata(metadata)

    encoder.dump_to_file(binned_items_path)
    logger.info("Dumped to file")


if __name__ == "__main__":
    main()
