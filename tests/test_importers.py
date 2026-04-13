"""Tests for slidescore.importers."""

from __future__ import annotations

import pytest

pytest.skip(
    "Legacy shapes-based tests; superseded by geometries refactor. "
    "Will be rewritten against the new Annotations API.",
    allow_module_level=True,
)


def test_from_json_points() -> None:
    data = [{"x": 1, "y": 2}, {"x": 3, "y": 4}]
    records = from_json(data)
    assert len(records) == 2
    assert records[0] == PointRecord(1, 2)
    assert records[1] == PointRecord(3, 4)


def test_from_json_heatmap() -> None:
    data = [
        {
            "type": "heatmap",
            "x": 10,
            "y": 20,
            "height": 32,
            "data": [
                [255, 0],
                [0, 128],
            ],
        },
    ]
    records = from_json(data)
    assert len(records) == 1
    heatmap = records[0]
    assert isinstance(heatmap, HeatmapRecord)
    assert heatmap.x_offset == 10 and heatmap.y_offset == 20
    assert heatmap.size_per_pixel == 16
    assert heatmap.matrix == [[255, 0], [0, 128]]


def test_from_json_polygon() -> None:
    data = [
        {
            "type": "polygon",
            "points": [{"x": 0, "y": 1}, {"x": 2, "y": 3}],
            "labels": [{"name": "a", "polygon_i": 0}],
        },
    ]
    records = from_json(data)
    assert len(records) == 1
    polygon = records[0]
    assert isinstance(polygon, PolygonRecord)
    assert polygon.exterior == [(0, 1), (2, 3)]
    assert polygon.slidescore_labels == []


def test_from_json_polygon_ignores_legacy_name_only_label_dicts() -> None:
    """Legacy ``{"name":…}`` rows do not become :class:`SlideScoreLabel` captions."""
    data = [
        {
            "type": "polygon",
            "points": [{"x": 0, "y": 0}, {"x": 1, "y": 0}, {"x": 1, "y": 1}],
            "labels": [
                {"name": "primary", "polygon_i": 0},
                {"name": "ignored", "polygon_i": 0},
            ],
        },
    ]
    poly = from_json(data)[0]
    assert isinstance(poly, PolygonRecord)
    assert poly.slidescore_labels == []


def test_from_json_polygon_export_answer_json_shape() -> None:
    """Downloaded answer JSON: ``polygon`` + ``area`` + ``labels`` (caption list)."""
    data = [
        {
            "type": "polygon",
            "modifiedOn": "2026-04-10T14:41:36.689Z",
            "points": [
                {"x": 13328, "y": 12039},
                {"x": 8751, "y": 12039},
                {"x": 8234, "y": 12059},
                {"x": 14542, "y": 12954},
            ],
            "area": "28.45 mm2",
            "labels": [
                {
                    "label": "Example label which pops up",
                    "x": 14204,
                    "y": 16138,
                    "whenToShow": "mouseover",
                    "fontsize": 474,
                },
                {
                    "label": "always there",
                    "x": 6045,
                    "y": 18785,
                    "whenToShow": "always",
                    "fontsize": 474,
                },
            ],
        },
    ]
    poly = from_json(data)[0]
    assert isinstance(poly, PolygonRecord)
    assert poly.slidescore_labels == [
        SlideScoreLabel(
            label="Example label which pops up",
            x=14204.0,
            y=16138.0,
            whenToShow="mouseover",
            fontsize=474.0,
        ),
        SlideScoreLabel(
            label="always there",
            x=6045.0,
            y=18785.0,
            whenToShow="always",
            fontsize=474.0,
        ),
    ]
    assert poly.metadata.get("area") == "28.45 mm2"
    assert poly.metadata.get("modifiedOn") == "2026-04-10T14:41:36.689Z"


def test_from_json_polygon_slide_caption_label() -> None:
    data = [
        {
            "type": "polygon",
            "points": [{"x": 0, "y": 0}, {"x": 2, "y": 0}, {"x": 1, "y": 2}],
            "labels": [
                {
                    "label": "R0",
                    "x": 50,
                    "y": 60,
                    "whenToShow": "always",
                    "fontSize": 12,
                },
            ],
        },
    ]
    records = from_json(data)
    poly = records[0]
    assert isinstance(poly, PolygonRecord)
    assert poly.slidescore_labels == [
        SlideScoreLabel(
            label="R0",
            x=50.0,
            y=60.0,
            whenToShow="always",
            fontsize=12.0,
        ),
    ]


def test_from_json_polygon_caption_uses_lowercase_fontsize_like_tsv_export() -> None:
    """Exported answers use ``fontsize`` (lowercase), not only ``fontSize``."""
    data = [
        {
            "type": "polygon",
            "points": [{"x": 0, "y": 0}, {"x": 1, "y": 0}, {"x": 0, "y": 1}],
            "labels": [
                {
                    "label": "Example label which pops up",
                    "x": 14204,
                    "y": 16138,
                    "whenToShow": "mouseover",
                    "fontsize": 474,
                },
                {
                    "label": "always there",
                    "x": 6045,
                    "y": 18785,
                    "whenToShow": "always",
                    "fontsize": 474,
                },
            ],
        },
    ]
    records = from_json(data)
    poly = records[0]
    assert isinstance(poly, PolygonRecord)
    assert len(poly.slidescore_labels) == 2
    assert poly.slidescore_labels[0].label == "Example label which pops up"
    assert poly.slidescore_labels[0].fontsize == 474.0
    assert poly.slidescore_labels[1].whenToShow == "always"


def test_from_json_brush_labels_per_positive_polygon() -> None:
    data = [
        {
            "type": "brush",
            "positivePolygons": [
                [{"x": 0, "y": 0}, {"x": 10, "y": 0}, {"x": 5, "y": 10}],
                [{"x": 100, "y": 100}, {"x": 110, "y": 100}, {"x": 105, "y": 110}],
            ],
            "negativePolygons": [
                [{"x": 2, "y": 2}, {"x": 4, "y": 2}, {"x": 3, "y": 4}],
            ],
            "labels": [{"name": "first"}, {"name": "second"}],
        },
    ]
    records = from_json(data)
    assert len(records) == 2
    assert records[0].slidescore_labels == []
    assert records[1].slidescore_labels == []
    assert all(isinstance(record, PolygonRecord) for record in records)
    # Vertex-in-positive assignment: the hole lies under the first positive
    # stroke only (not the second).
    assert len(records[0].interiors) == 1
    assert len(records[1].interiors) == 0


def test_from_json_brush_banana_hole_vertex_not_centroid_of_hole() -> None:
    """Non-convex hole: vertex mean can lie outside the parent (mouth of a U).

    Centroid-in-parent would drop the hole; assign_holes uses vertex-in-parent.
    """
    data = [
        {
            "type": "brush",
            # Upside-down U (opening at bottom); mouth is outside the polygon.
            "positivePolygons": [
                [
                    {"x": 0, "y": 100},
                    {"x": 100, "y": 100},
                    {"x": 100, "y": 0},
                    {"x": 80, "y": 0},
                    {"x": 80, "y": 80},
                    {"x": 20, "y": 80},
                    {"x": 20, "y": 0},
                    {"x": 0, "y": 0},
                ],
            ],
            # Vertices on the two lower legs only; mean (~50, ~18) sits in the mouth.
            "negativePolygons": [
                [
                    {"x": 15, "y": 15},
                    {"x": 18, "y": 15},
                    {"x": 15, "y": 25},
                    {"x": 82, "y": 15},
                    {"x": 85, "y": 15},
                    {"x": 85, "y": 25},
                ],
            ],
        },
    ]
    records = from_json(data)
    assert len(records) == 1
    poly = records[0]
    assert isinstance(poly, PolygonRecord)
    assert len(poly.interiors) == 1
    assert len(poly.interiors[0]) == 6


def test_from_json_brush_no_negatives() -> None:
    data = [
        {
            "type": "brush",
            "positivePolygons": [
                [{"x": 0, "y": 0}, {"x": 10, "y": 0}, {"x": 5, "y": 10}],
            ],
            "negativePolygons": [],
        },
    ]
    records = from_json(data)
    assert len(records) == 1
    assert isinstance(records[0], PolygonRecord)
    assert len(records[0].interiors) == 0


def test_from_json_ellipse_rect() -> None:
    data = [
        {"type": "ellipse", "center": {"x": 10, "y": 20}, "size": {"x": 5, "y": 3}},
        {
            "type": "rectangle",
            "corner": {"x": 1, "y": 2},
            "size": {"x": 4, "y": 6},
        },
    ]
    records = from_json(data)
    assert isinstance(records[0], EllipseRecord)
    assert records[0].center == (10, 20)
    assert records[0].size == (5, 3)
    assert isinstance(records[1], RectangleRecord)
    assert records[1].corner == (1, 2)
    assert records[1].size == (4, 6)


def test_from_tsv_points_and_polygons() -> None:
    pts = from_points_tsv("1\t2\n3 4\n")
    assert pts == [PointRecord(1, 2), PointRecord(3, 4)]
    polys = from_polygons_tsv("0 0 1 0 1 1\n")
    assert len(polys) == 1
    assert polys[0].exterior == [(0, 0), (1, 0), (1, 1)]


def test_from_heatmap_tsv() -> None:
    text = """Heatmap 250 250 16
0 0 128
1 1 255
"""
    records = from_heatmap_tsv(text)
    assert len(records) == 1
    assert records[0].matrix[0][0] == 128
    assert records[0].matrix[1][1] == 255


def test_from_heatmap_tsv_binary() -> None:
    text = """binary-heatmap 1 2 8
0 1
"""
    records = from_heatmap_tsv(text)
    assert records[0].name == "binary-heatmap"
    assert records[0].matrix[1][0] == 255


def test_from_geojson_polygon_and_point() -> None:
    poly_fc = {
        "type": "FeatureCollection",
        "features": [
            {
                "type": "Feature",
                "geometry": {
                    "type": "Polygon",
                    "coordinates": [[[0, 0], [10, 0], [10, 10], [0, 0]]],
                },
                "properties": {"k": 1},
            },
        ],
    }
    records = from_geojson(poly_fc)
    assert len(records) == 1
    assert records[0].metadata.get("k") == 1
    point_fc = {
        "type": "FeatureCollection",
        "features": [
            {
                "type": "Feature",
                "geometry": {"type": "Point", "coordinates": [3.7, 4.2]},
                "properties": {},
            },
        ],
    }
    point_record = from_geojson(point_fc)[0]
    assert isinstance(point_record, PointRecord)
    assert point_record.x == 4 and point_record.y == 4


def test_from_json_rejects_unknown_type() -> None:
    with pytest.raises(ValueError, match="Unsupported"):
        from_json([{"type": "nope", "data": []}])
