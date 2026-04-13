"""Anno2 encode -> decode round-trip tests.

These are the highest-value tests in the SDK: they verify that the full
pipeline (records -> containers -> encode ZIP -> decode ZIP -> containers
-> records) preserves data.
"""

from __future__ import annotations

import pytest

pytest.skip(
    "Legacy shapes-based roundtrip tests; superseded by geometries refactor. "
    "Will be rewritten against Annotations.to_anno2 / Annotations.from_anno2.",
    allow_module_level=True,
)


def _encode_decode_records(records, **encode_kwargs):
    """Helper: records -> containers -> encode -> decode -> containers -> records."""
    container = to_containers(records)
    with tempfile.TemporaryDirectory() as tmpdir:
        path = Path(tmpdir) / "test.zip"
        encode(container, path, **encode_kwargs)
        decoded = decode(path)
    return from_containers(decoded)


class TestPointsRoundTrip:
    def test_few_points_json_path(self) -> None:
        """Few points go through anno1_points.json.br (JSON fallback)."""
        src = [PointRecord(100, 200), PointRecord(300, 400)]
        back = _encode_decode_records(src)
        assert len(back) == 2
        coords = {(point.x, point.y) for point in back}
        assert (100, 200) in coords
        assert (300, 400) in coords

    def test_mask_points_round_trip(self) -> None:
        """Dense mask-style points go through masks.tar.gz."""
        # Generate enough points in a small area to trigger mask path
        src = [PointRecord(x, y) for x in range(50) for y in range(50)]
        container = to_containers(src)
        container.name = "mask"
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "test.zip"
            encode(container, path)
            decoded = decode(path)
        back = from_containers(decoded)
        original_coords = {(point.x, point.y) for point in src}
        decoded_coords = {(point.x, point.y) for point in back}
        assert decoded_coords == original_coords


class TestPolygonsRoundTrip:
    def test_simple_polygon(self) -> None:
        src = [
            PolygonRecord(exterior=[(10, 10), (200, 10), (200, 200), (10, 200)]),
        ]
        back = _encode_decode_records(src)
        assert len(back) == 1
        restored = back[0]
        assert isinstance(restored, PolygonRecord)
        # Simplification may alter vertex count, but the polygon should
        # still cover approximately the same area
        assert len(restored.exterior) >= 3

    def test_polygon_with_hole(self) -> None:
        src = [
            PolygonRecord(
                exterior=[(0, 0), (200, 0), (200, 200), (0, 200)],
                interiors=[[(50, 50), (150, 50), (150, 150), (50, 150)]],
            ),
        ]
        container = to_containers(src)
        assert isinstance(container, Polygons)
        # Verify holes are stored in the container
        assert len(container.negative_polygons_i) > 0

        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "test.zip"
            encode(container, path)
            decoded = decode(path)

        assert isinstance(decoded, Polygons)
        back = from_containers(decoded)
        # Holes don't surface as top-level records
        assert len(back) == 1

    def test_multiple_polygons(self) -> None:
        src = [
            PolygonRecord(exterior=[(10, 10), (100, 10), (100, 100), (10, 100)]),
            PolygonRecord(exterior=[(500, 500), (600, 500), (600, 600), (500, 600)]),
        ]
        back = _encode_decode_records(src)
        assert len(back) == 2

    def test_polygon_caption_labels_round_trip(self) -> None:
        """labels.json carries caption dicts with polygon_i (SlideScore wire)."""
        cap = SlideScoreLabel(
            label="on-slide",
            x=12.5,
            y=34.0,
            whenToShow="always",
            fontsize=11,
        )
        src = [
            PolygonRecord(
                exterior=[(10, 10), (200, 10), (200, 200), (10, 200)],
                slidescore_labels=[cap],
            ),
        ]
        back = _encode_decode_records(src)
        assert len(back) == 1
        restored = back[0]
        assert isinstance(restored, PolygonRecord)
        assert restored.slidescore_labels == [cap]

    def test_ellipse_shape_overlay_round_trip(self) -> None:
        """EllipseRecord -> ZIP (shape_overlay.json) -> EllipseRecord."""
        src = [EllipseRecord(center=(100, 100), size=(30, 20))]
        back = _encode_decode_records(src)
        assert len(back) == 1
        restored = back[0]
        assert isinstance(restored, EllipseRecord)
        assert restored.center == (100, 100)
        assert restored.size == (30, 20)
        assert restored.slidescore_labels == []

    def test_rect_shape_overlay_round_trip(self) -> None:
        """RectangleRecord -> ZIP (shape_overlay.json) -> RectangleRecord."""
        src = [RectangleRecord(corner=(10, 20), size=(50, 60))]
        back = _encode_decode_records(src)
        assert len(back) == 1
        restored = back[0]
        assert isinstance(restored, RectangleRecord)
        assert restored.corner == (10, 20)
        assert restored.size == (50, 60)
        assert restored.slidescore_labels == []

    def test_polygon_zip_includes_shape_overlay_sidecar(self) -> None:
        src = [EllipseRecord(center=(100, 100), size=(30, 20))]
        container = to_containers(src)
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "e.zip"
            encode(container, path)
            with zipfile.ZipFile(path) as zf:
                assert "polygon_container/shape_overlay.json" in zf.namelist()

    def test_mixed_polygon_and_ellipse_round_trip(self) -> None:
        src = [
            PolygonRecord(exterior=[(0, 0), (10, 0), (10, 10), (0, 10)]),
            EllipseRecord(center=(50, 50), size=(5, 5)),
        ]
        back = _encode_decode_records(src)
        assert len(back) == 2
        assert isinstance(back[0], PolygonRecord)
        assert isinstance(back[1], EllipseRecord)
        assert back[1].center == (50, 50) and back[1].size == (5, 5)


class TestHeatmapRoundTrip:
    def test_simple_heatmap(self) -> None:
        src = [
            HeatmapRecord(
                matrix=[[0, 128, 255], [64, 0, 32]],
                x_offset=10,
                y_offset=20,
                size_per_pixel=8,
            ),
        ]
        back = _encode_decode_records(src)
        assert len(back) == 1
        heatmap_record = back[0]
        assert isinstance(heatmap_record, HeatmapRecord)
        assert heatmap_record.matrix == [[0, 128, 255], [64, 0, 32]]
        assert heatmap_record.x_offset == 10
        assert heatmap_record.y_offset == 20
        assert heatmap_record.size_per_pixel == 8

    def test_heatmap_name_preserved(self) -> None:
        src = [
            HeatmapRecord(
                matrix=[[1, 0], [0, 1]],
                x_offset=0,
                y_offset=0,
                size_per_pixel=4,
                name="binary-heatmap",
            ),
        ]
        back = _encode_decode_records(src)
        assert len(back) == 1
        # The container carries the name; from_containers restores it
        assert back[0].name == "binary-heatmap"
