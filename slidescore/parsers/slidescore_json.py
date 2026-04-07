from __future__ import annotations

import math

from ..lib.AnnoClasses import Heatmap, Points, Polygons


def read_slidescore_json(data) -> Points | Polygons | Heatmap:
    """Parse a SlideScore front-end annotation JSON into annotation containers.

    Supported types: points (flat ``{x,y}`` list), heatmap, polygon, brush,
    ellipse, rect. Raises on unsupported types or empty/non-list input.

    WARNING: All information except coordinates is lost (e.g. ``label`` data
    for brush entries is assigned to the first positive polygon only).
    """
    if not isinstance(data, list):
        raise Exception("Expected a list as data")

    if len(data) == 0:
        raise Exception("Data is an empty list, cannot convert")

    # Points are stored as a raw list of xy pairs without a "type" key
    if "type" not in data[0]:
        if "x" in data[0] and "y" in data[0]:
            items = Points()
            items.name = "points"
            for point in data:
                x = int(point["x"])
                y = int(point["y"])
                items.addPoint(x, y)
            return items
        else:
            raise Exception("Unsupported slidescore JSON: type not specified")

    if data[0]["type"] == "heatmap":
        x_offset = data[0]["x"] if "x" in data[0] else 0
        y_offset = data[0]["y"] if "y" in data[0] else 0
        items = Heatmap(
            data=data[0]["data"],
            x_offset=x_offset,
            y_offset=y_offset,
            size_per_pixel=round(data[0]["height"] / len(data[0]["data"])),
        )
        return items

    items = Polygons()
    for entry in data:
        if entry["type"].lower() == "polygon":
            cur_polygon = []
            for point in entry["points"]:
                x, y = round(point["x"]), round(point["y"])
                cur_polygon.extend([x, y])
            polygon_i = items.addPolygon(cur_polygon)
            if "labels" in entry:
                for label in entry["labels"]:
                    label["polygon_i"] = polygon_i
                    items.labels.append(label)
        elif entry["type"].lower() == "brush":
            pos_polygon_is = []
            for polygon in entry["positivePolygons"]:
                cur_polygon = []
                for point in polygon:
                    x, y = round(point["x"]), round(point["y"])
                    cur_polygon.extend([x, y])
                pos_polygon_i = items.addPolygon(cur_polygon)
                pos_polygon_is.append(pos_polygon_i)
            for neg_polygon in entry["negativePolygons"]:
                cur_neg_polygon = []
                for point in neg_polygon:
                    x, y = round(point["x"]), round(point["y"])
                    cur_neg_polygon.extend([x, y])
                neg_polygon_i = items.addPolygon(cur_neg_polygon)
                for pos_polygon_i in pos_polygon_is:
                    items.linkPosPolygonToNegPolygon(pos_polygon_i, neg_polygon_i)
            if "labels" in entry:
                for label in entry["labels"]:
                    label["polygon_i"] = pos_polygon_is[0]
                    items.labels.append(label)
        elif entry["type"].lower() == "ellipse":
            center = entry["center"]
            size = entry["size"]
            retq1 = []
            retq2 = []
            retq3 = []
            retq4 = []
            n = 10
            for i in range(n):
                theta = math.pi / 2 * i / n
                fi = math.pi - math.atan(
                    math.tan(theta) * math.sqrt(size["x"] / size["y"])
                )
                cos = size["x"] * math.cos(fi)
                sin = size["y"] * math.sin(fi)
                x = round(center["x"] + cos)
                y = round(center["y"] + sin)
                retq1.append([x, y])
                x = round(center["x"] - cos)
                y = round(center["y"] + sin)
                retq2.append([x, y])
                x = round(center["x"] - cos)
                y = round(center["y"] - sin)
                retq3.append([x, y])
                x = round(center["x"] + cos)
                y = round(center["y"] - sin)
                retq4.append([x, y])
            retq2.reverse()
            retq4.reverse()
            cur_polygon = []
            for p in retq1:
                cur_polygon.extend([p[0], p[1]])
            for p in retq2:
                cur_polygon.extend([p[0], p[1]])
            for p in retq3:
                cur_polygon.extend([p[0], p[1]])
            for p in retq4:
                cur_polygon.extend([p[0], p[1]])
            polygon_i = items.addPolygon(cur_polygon)
            if "labels" in entry:
                for label in entry["labels"]:
                    label["polygon_i"] = polygon_i
                    items.labels.append(label)
        elif entry["type"].lower() == "rect":
            corner = entry["corner"]
            size = entry["size"]
            cur_polygon = [
                round(corner["x"]),
                round(corner["y"]),
                round(corner["x"] + size["x"]),
                round(corner["y"]),
                round(corner["x"] + size["x"]),
                round(corner["y"] + size["y"]),
                round(corner["x"]),
                round(corner["y"] + size["y"]),
            ]
            polygon_i = items.addPolygon(cur_polygon)
            if "labels" in entry:
                for label in entry["labels"]:
                    label["polygon_i"] = polygon_i
                    items.labels.append(label)
        else:
            raise Exception(
                f'Unsupported slidescore JSON type: "{entry["type"]}" not supported'
            )
    return items
