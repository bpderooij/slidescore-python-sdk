
import argparse
import gzip
import json
import logging

from .lib.Encoder import Encoder
from .parsers.geojson import read_geo_json
from .parsers.slidescore_json import read_slidescore_json
from .parsers.tsv import read_tsv

DESC = """
This program converts a items TSV file (or slidescore_anno1.json) of either points in a mask, polygons or a heatmap, into a binned format for fast lookup.
Author: Bart.
"""

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

    # Parse the input items
    if raw_items_path.endswith(".tsv"):
        items = read_tsv(raw_items_path, args.points_type, args.experimental)
    elif raw_items_path.endswith(".geojson"):
        items = read_geo_json(raw_items_path)
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
