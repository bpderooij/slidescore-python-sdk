from __future__ import annotations

import json
import logging

from ..lib.AnnoClasses import Points, Polygons

_logger = logging.getLogger(__name__)


def read_geo_json(path: str) -> Points | Polygons:
    """Read a QuPath GeoJSON file containing only polygons or points.

    Returns a :class:`Points` instance when only points are present, a
    :class:`Polygons` instance when only polygons are present. When both are
    found, logs a warning and returns the polygons only.
    """
    polygons = Polygons()
    points = Points()

    with open(path) as fh:
        data = json.load(fh)

    for metadata, positive_vertices, negative_vertices_list in extract_geojson(data):
        if len(positive_vertices) == 1:
            point = positive_vertices[0]
            x, y = round(point[0]), round(point[1])
            points.addPoint(x, y)
            if metadata is not None:
                points.metadata[f"{x},{y}"] = metadata
        else:
            cur_polygon = []
            for point in positive_vertices:
                x, y = round(point[0]), round(point[1])
                cur_polygon.extend([x, y])
            pos_polygon_i = polygons.addPolygon(cur_polygon)

            if metadata is not None:
                polygons.metadata[pos_polygon_i] = metadata

            for negative_vertices in negative_vertices_list:
                cur_neg_polygon = []
                for point in negative_vertices:
                    x, y = round(point[0]), round(point[1])
                    cur_neg_polygon.extend([x, y])
                neg_polygon_i = polygons.addPolygon(cur_neg_polygon)
                polygons.linkPosPolygonToNegPolygon(pos_polygon_i, neg_polygon_i)

    if len(points) == 0 and len(polygons) == 0:
        raise Exception("No points or polygons loaded from GeoJSON")

    if len(points) != 0 and len(polygons) == 0:
        return points

    if len(points) == 0 and len(polygons) != 0:
        return polygons

    _logger.warning(
        "Detected BOTH points and polygons in GeoJSON, only continuing with polygons"
    )
    _logger.warning("Please remove the points from the GeoJSON to prevent ambiguity")
    return polygons


def extract_geojson(data):
    """Yield ``(metadata, positive_vertices, [negative_vertices, …])`` for each feature.

    Handles Polygon, MultiPolygon, and Point geometry types from QuPath GeoJSON.
    If ``positiveVertices`` has length 1, the caller should treat it as a point.
    https://datatracker.ietf.org/doc/html/rfc7946
    """
    for feature in data["features"]:
        if "geometry" not in feature:
            continue
        metadata = feature.get("properties")

        geometry = feature["geometry"]
        if geometry["type"] == "Polygon":
            yield (metadata, geometry["coordinates"][0], geometry["coordinates"][1:])

            if "nucleusGeometry" not in feature:
                continue
            nucl_geometry = feature["nucleusGeometry"]
            if nucl_geometry["type"] != "Polygon":
                continue
            yield (
                metadata,
                nucl_geometry["coordinates"][0],
                nucl_geometry["coordinates"][1:],
            )
        elif geometry["type"] == "MultiPolygon":
            for polygon in geometry["coordinates"]:
                yield (None, polygon[0], polygon[1:])
        elif geometry["type"] == "Point":
            # coordinates is [x, y]; yield once as a single-point polygon
            yield (metadata, [geometry["coordinates"]], [])
