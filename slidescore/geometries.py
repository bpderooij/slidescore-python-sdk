"""Geometry domain model for the SlideScore SDK (v2).

This module is a leaf: it has no ``anno2`` imports. It is called from the
``Annotations`` collection (introduced in step 6 of the shapes-layering
refactor).
"""

from __future__ import annotations

import copy
import math
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Protocol, TypeAlias, runtime_checkable

import numpy as np
import numpy.typing as npt

__all__ = [
    "Color",
    "Ellipse",
    "Geometry",
    "Heatmap",
    "MultiPolygon",
    "Point",
    "Polygon",
    "PolygonLike",
    "Rectangle",
    "SlideScoreLabel",
    "parse_color",
]


# ---------------------------------------------------------------------------
# Color
# ---------------------------------------------------------------------------


#: Hex string (e.g. ``"#rrggbb"`` / ``"#rrggbbaa"``) or an RGB / RGBA int tuple.
Color: TypeAlias = str | tuple[int, int, int] | tuple[int, int, int, int]


def parse_color(raw: object) -> Color | None:
    """Normalize a wire-format color value to :data:`Color` or ``None``.

    Accepts:

    - ``None`` → ``None``
    - ``str`` (e.g. ``"#rrggbb"``) → stripped string
    - length-3 or length-4 iterable of ints → RGB / RGBA tuple

    Anything else (including malformed tuples) returns ``None``.
    """
    if raw is None:
        return None
    if isinstance(raw, str):
        return raw.strip()
    if isinstance(raw, (list, tuple)) and len(raw) in (3, 4):
        try:
            return tuple(int(component) for component in raw)  # type: ignore[return-value]
        except (TypeError, ValueError):
            return None
    return None


# ---------------------------------------------------------------------------
# SlideScore labels[] caption row (typography on slide)
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class SlideScoreLabel:
    """One caption dict from the annotation ``labels`` array (on-slide typography).

    Same keys as SlideScore JSON, e.g.
    ``{"label":"Example label which pops up","x":14204,"y":16138,
    "whenToShow":"mouseover","fontsize":474}``.
    """

    label: str
    x: float
    y: float
    whenToShow: str
    fontsize: int

    def to_wire_dict(self) -> dict[str, Any]:
        """Serialize to one caption object (no ``polygon_i``; encoder adds that)."""
        return {
            "label": self.label,
            "x": self.x,
            "y": self.y,
            "whenToShow": self.whenToShow,
            "fontsize": self.fontsize,
        }


# ---------------------------------------------------------------------------
# Geometry ABC
# ---------------------------------------------------------------------------


@dataclass
class Geometry(ABC):
    """Abstract base class for all SlideScore geometries.

    Shared attributes are keyword-only so concrete subclasses can use
    positional fields for their geometry data.

    Geometries are **mutable**: :meth:`translate`, :meth:`scale`, and
    (on :class:`Polygon`) :meth:`~Polygon.simplify` modify in place.
    Use :func:`copy.copy` for an independent copy; mutating the result
    will not affect the original.

    ``area`` and ``modified_on`` round-trip SlideScore answer-JSON fields.
    ``area`` is kept as the display string ("3.96 mm2") because SlideScore
    can emit different units; we don't parse it. Both default to ``None``
    and are populated only by wire-format importers.

    ``slidescore_labels`` holds on-slide caption rows (``SlideScoreLabel``)
    attached to this geometry. Captions carry their own ``(x, y)`` so they
    render at the author-picked position, not the geometry's centroid.
    """

    label: str | None = field(default=None, kw_only=True)
    color: Color | None = field(default=None, kw_only=True)
    metadata: dict[str, Any] = field(default_factory=dict, kw_only=True)
    area: str | None = field(default=None, kw_only=True)
    modified_on: str | None = field(default=None, kw_only=True)
    slidescore_labels: list[SlideScoreLabel] = field(
        default_factory=list, kw_only=True
    )

    @abstractmethod
    def bounds(self) -> tuple[float, float, float, float]:
        """Axis-aligned bounding box as ``(x_min, y_min, x_max, y_max)``."""

    @abstractmethod
    def translate(self, dx: float, dy: float) -> None:
        """Translate the geometry in place by ``(dx, dy)``."""

    @abstractmethod
    def scale(self, factor: float) -> None:
        """Scale the geometry in place about the origin by ``factor``."""

    def __copy__(self) -> Geometry:
        # Geometries are almost always handled by value, and mutable
        # container fields (exterior list, interiors list-of-lists,
        # metadata dict, numpy matrix) would alias under a naïve shallow
        # copy. Return a deep copy so the result is safe to mutate.
        return copy.deepcopy(self)


# ---------------------------------------------------------------------------
# Point
# ---------------------------------------------------------------------------


@dataclass
class Point(Geometry):
    """A single point annotation in slide-pixel coordinates."""

    x: float
    y: float

    def bounds(self) -> tuple[float, float, float, float]:
        return (self.x, self.y, self.x, self.y)

    def translate(self, dx: float, dy: float) -> None:
        self.x += dx
        self.y += dy

    def scale(self, factor: float) -> None:
        self.x *= factor
        self.y *= factor


# ---------------------------------------------------------------------------
# Polygon
# ---------------------------------------------------------------------------


@dataclass
class Polygon(Geometry):
    """A polygon with optional interior holes.

    ``exterior`` is the outer boundary as ``[(x, y), ...]``. ``interiors``
    is a list of inner rings (holes); each interior ring has the same
    ``[(x, y), ...]`` shape. For SlideScore brush annotations, each
    positive stroke becomes one :class:`Polygon` and its matching
    negative strokes become :attr:`interiors` entries — see
    :meth:`assign_holes`.
    """

    exterior: list[tuple[float, float]]
    interiors: list[list[tuple[float, float]]] = field(default_factory=list)

    # -- geometry primitives -------------------------------------------------

    def bounds(self) -> tuple[float, float, float, float]:
        if not self.exterior:
            return (0.0, 0.0, 0.0, 0.0)
        xs = [x for x, _ in self.exterior]
        ys = [y for _, y in self.exterior]
        return (min(xs), min(ys), max(xs), max(ys))

    @property
    def centroid(self) -> tuple[float, float]:
        """Area-weighted polygon centroid via the shoelace formula.

        Falls back to the arithmetic mean of vertices for degenerate
        (zero-area) polygons. Interior rings are not subtracted — this
        returns the centroid of the outer ring only.
        """
        vertices = self.exterior
        n = len(vertices)
        if n == 0:
            return (0.0, 0.0)
        if n < 3:
            mean_x = sum(x for x, _ in vertices) / n
            mean_y = sum(y for _, y in vertices) / n
            return (mean_x, mean_y)
        two_area = 0.0
        cx = 0.0
        cy = 0.0
        for i in range(n):
            x0, y0 = vertices[i]
            x1, y1 = vertices[(i + 1) % n]
            cross = x0 * y1 - x1 * y0
            two_area += cross
            cx += (x0 + x1) * cross
            cy += (y0 + y1) * cross
        if two_area == 0.0:
            mean_x = sum(x for x, _ in vertices) / n
            mean_y = sum(y for _, y in vertices) / n
            return (mean_x, mean_y)
        area_times_six = 3.0 * two_area
        return (cx / area_times_six, cy / area_times_six)

    def contains(self, x: float, y: float) -> bool:
        """Point-in-polygon test honoring interior holes.

        Returns ``True`` iff ``(x, y)`` is inside :attr:`exterior` and
        not inside any ring in :attr:`interiors`. Uses a standard
        ray-casting algorithm; points exactly on an edge are treated
        ambiguously.
        """
        if not _point_in_ring(x, y, self.exterior):
            return False
        for ring in self.interiors:
            if _point_in_ring(x, y, ring):
                return False
        return True

    # -- mutation ------------------------------------------------------------

    def translate(self, dx: float, dy: float) -> None:
        self.exterior = [(x + dx, y + dy) for x, y in self.exterior]
        self.interiors = [
            [(x + dx, y + dy) for x, y in ring] for ring in self.interiors
        ]

    def scale(self, factor: float) -> None:
        self.exterior = [(x * factor, y * factor) for x, y in self.exterior]
        self.interiors = [
            [(x * factor, y * factor) for x, y in ring] for ring in self.interiors
        ]

    def simplify(self, tolerance: float) -> None:
        """Simplify all rings in place with Douglas-Peucker.

        ``tolerance`` is the maximum perpendicular deviation in pixel
        space. A non-positive tolerance is a no-op.
        """
        if tolerance <= 0:
            return
        self.exterior = _douglas_peucker(self.exterior, tolerance)
        self.interiors = [_douglas_peucker(ring, tolerance) for ring in self.interiors]

    def assign_holes(self, rings: list[list[tuple[float, float]]]) -> None:
        """Attach candidate holes that fit inside this polygon's exterior.

        For each ring in ``rings``, if **any** of its vertices lies
        inside :attr:`exterior`, the ring is appended to :attr:`interiors`
        and removed from ``rings``. Consuming the list means the same
        ring cannot be assigned twice when this method is called across
        a sequence of sibling polygons.

        Vertex-in-parent is used rather than centroid-in-parent: the
        centroid of a non-convex hole (e.g. a crescent) can fall outside
        the hole itself, defeating the test. Testing any vertex is
        sufficient for SlideScore brush data because holes never cross
        their parent's boundary.
        """
        kept: list[list[tuple[float, float]]] = []
        for ring in rings:
            if any(_point_in_ring(vx, vy, self.exterior) for vx, vy in ring):
                self.interiors.append(ring)
            else:
                kept.append(ring)
        rings[:] = kept

    def to_polygon(self) -> Polygon:
        return self


# ---------------------------------------------------------------------------
# MultiPolygon
# ---------------------------------------------------------------------------


@dataclass
class MultiPolygon(Geometry):
    """A set of polygons that form one logical unit (a brush stroke).

    Each member :class:`Polygon` keeps its own ``exterior``, ``interiors``,
    ``color``, ``metadata``, and ``slidescore_labels``. Brush-level shared
    fields (``area``, ``modified_on``) live on the :class:`MultiPolygon`
    itself via the :class:`Geometry` base.

    Caption attribution: on wire import, each brush caption is assigned to
    the **member whose exterior contains the caption's ``(x, y)``** —
    SlideScore places captions by author-picked coordinate, not by member
    index, so index-based attribution is wrong for brushes with more or
    fewer labels than positive rings.
    """

    members: list[Polygon] = field(default_factory=list)

    def bounds(self) -> tuple[float, float, float, float]:
        if not self.members:
            return (0.0, 0.0, 0.0, 0.0)
        xs_min, ys_min, xs_max, ys_max = zip(
            *(member.bounds() for member in self.members), strict=True
        )
        return (min(xs_min), min(ys_min), max(xs_max), max(ys_max))

    def translate(self, dx: float, dy: float) -> None:
        for member in self.members:
            member.translate(dx, dy)

    def scale(self, factor: float) -> None:
        for member in self.members:
            member.scale(factor)


# ---------------------------------------------------------------------------
# Rectangle
# ---------------------------------------------------------------------------


@dataclass
class Rectangle(Geometry):
    """Axis-aligned rectangle.

    ``corner`` is the top-left ``(x, y)`` vertex; ``size`` is
    ``(width, height)``.
    """

    corner: tuple[float, float]
    size: tuple[float, float]

    def bounds(self) -> tuple[float, float, float, float]:
        x0, y0 = self.corner
        width, height = self.size
        return (x0, y0, x0 + width, y0 + height)

    def translate(self, dx: float, dy: float) -> None:
        x0, y0 = self.corner
        self.corner = (x0 + dx, y0 + dy)

    def scale(self, factor: float) -> None:
        x0, y0 = self.corner
        width, height = self.size
        self.corner = (x0 * factor, y0 * factor)
        self.size = (width * factor, height * factor)

    def to_polygon(self) -> Polygon:
        x0, y0 = self.corner
        width, height = self.size
        return Polygon(
            exterior=[
                (x0, y0),
                (x0 + width, y0),
                (x0 + width, y0 + height),
                (x0, y0 + height),
            ],
            label=self.label,
            color=self.color,
            metadata=dict(self.metadata),
            area=self.area,
            modified_on=self.modified_on,
            slidescore_labels=list(self.slidescore_labels),
        )


# ---------------------------------------------------------------------------
# Ellipse
# ---------------------------------------------------------------------------


@dataclass
class Ellipse(Geometry):
    """Axis-aligned (unrotated) ellipse.

    ``center`` is the ``(x, y)`` pixel center. ``size`` holds the
    **semi-axis** lengths (half-width, half-height). SlideScore does
    not store rotated ellipses.
    """

    center: tuple[float, float]
    size: tuple[float, float]

    def bounds(self) -> tuple[float, float, float, float]:
        cx, cy = self.center
        rx, ry = self.size
        return (cx - rx, cy - ry, cx + rx, cy + ry)

    def translate(self, dx: float, dy: float) -> None:
        cx, cy = self.center
        self.center = (cx + dx, cy + dy)

    def scale(self, factor: float) -> None:
        cx, cy = self.center
        rx, ry = self.size
        self.center = (cx * factor, cy * factor)
        self.size = (rx * factor, ry * factor)

    def to_polygon(self, *, n_segments: int = 100) -> Polygon:
        """Discretize this ellipse into a closed polygon.

        Produces ``n_segments`` evenly spaced vertices on the boundary.
        Raises :class:`ValueError` if either semi-axis is non-positive
        or if ``n_segments`` is below 3.
        """
        cx, cy = self.center
        rx, ry = self.size
        if rx <= 0 or ry <= 0:
            raise ValueError("Ellipse size components must be positive")
        if n_segments < 3:
            raise ValueError("n_segments must be at least 3")
        exterior: list[tuple[float, float]] = []
        for segment_index in range(n_segments):
            t = 2 * math.pi * segment_index / n_segments
            exterior.append((cx + rx * math.cos(t), cy + ry * math.sin(t)))
        return Polygon(
            exterior=exterior,
            label=self.label,
            color=self.color,
            metadata=dict(self.metadata),
            area=self.area,
            modified_on=self.modified_on,
            slidescore_labels=list(self.slidescore_labels),
        )


# ---------------------------------------------------------------------------
# Heatmap
# ---------------------------------------------------------------------------


@dataclass
class Heatmap(Geometry):
    """Raster heatmap positioned in slide-pixel space.

    ``matrix`` is a 2-D ``uint8`` numpy array of shape ``(rows, cols)``.
    The spatial footprint is
    ``(x_offset, y_offset) → (x_offset + cols * size_per_pixel,
    y_offset + rows * size_per_pixel)``.

    ``name`` controls the anno2 ZIP layout type (``"heatmap"``,
    ``"binary-heatmap"``, …).
    """

    matrix: npt.NDArray[np.uint8]
    x_offset: float
    y_offset: float
    size_per_pixel: float
    name: str = "heatmap"

    def __post_init__(self) -> None:
        if not isinstance(self.matrix, np.ndarray):
            self.matrix = np.asarray(self.matrix)
        if self.matrix.ndim != 2:
            raise ValueError(
                f"Heatmap.matrix must be 2-D, got shape {self.matrix.shape}"
            )
        if self.matrix.dtype != np.uint8:
            if self.matrix.size:
                arr_min = int(self.matrix.min())
                arr_max = int(self.matrix.max())
                if arr_min < 0 or arr_max > 255:
                    raise ValueError(
                        f"Heatmap values must be in 0-255, got "
                        f"min={arr_min}, max={arr_max}"
                    )
            self.matrix = self.matrix.astype(np.uint8)

    def bounds(self) -> tuple[float, float, float, float]:
        rows, cols = self.matrix.shape
        return (
            self.x_offset,
            self.y_offset,
            self.x_offset + cols * self.size_per_pixel,
            self.y_offset + rows * self.size_per_pixel,
        )

    def translate(self, dx: float, dy: float) -> None:
        self.x_offset += dx
        self.y_offset += dy

    def scale(self, factor: float) -> None:
        self.x_offset *= factor
        self.y_offset *= factor
        self.size_per_pixel *= factor


# ---------------------------------------------------------------------------
# PolygonLike protocol
# ---------------------------------------------------------------------------


@runtime_checkable
class PolygonLike(Protocol):
    """Structural type for shapes convertible to a :class:`Polygon`.

    Implemented by :class:`Polygon`, :class:`Rectangle`, and
    :class:`Ellipse`. There is **no** class inheritance between the
    shape types — an :class:`Ellipse` is not a :class:`Polygon`, it
    merely knows how to become one.
    """

    def to_polygon(self) -> Polygon: ...

    def bounds(self) -> tuple[float, float, float, float]: ...


# ---------------------------------------------------------------------------
# Private helpers
# ---------------------------------------------------------------------------


def _point_in_ring(
    px: float,
    py: float,
    ring: list[tuple[float, float]],
) -> bool:
    """Ray-casting point-in-polygon test against a single ring."""
    n = len(ring)
    if n < 3:
        return False
    inside = False
    j = n - 1
    for i in range(n):
        xi, yi = ring[i]
        xj, yj = ring[j]
        if ((yi > py) != (yj > py)) and (
            px < (xj - xi) * (py - yi) / (yj - yi) + xi
        ):
            inside = not inside
        j = i
    return inside


def _douglas_peucker(
    points: list[tuple[float, float]],
    tolerance: float,
) -> list[tuple[float, float]]:
    """Iterative Douglas-Peucker polyline simplification.

    Endpoints are always preserved. Iterative rather than recursive to
    avoid Python's recursion limit on large polygons.
    """
    n = len(points)
    if n < 3:
        return list(points)

    keep = [False] * n
    keep[0] = True
    keep[-1] = True

    stack: list[tuple[int, int]] = [(0, n - 1)]
    while stack:
        start, end = stack.pop()
        if end <= start + 1:
            continue
        max_distance = -1.0
        max_index = start
        start_point = points[start]
        end_point = points[end]
        for i in range(start + 1, end):
            distance = _perpendicular_distance(points[i], start_point, end_point)
            if distance > max_distance:
                max_distance = distance
                max_index = i
        if max_distance > tolerance:
            keep[max_index] = True
            stack.append((start, max_index))
            stack.append((max_index, end))

    return [points[i] for i in range(n) if keep[i]]


def _perpendicular_distance(
    point: tuple[float, float],
    line_start: tuple[float, float],
    line_end: tuple[float, float],
) -> float:
    """Distance from *point* to the infinite line through the two endpoints."""
    px, py = point
    x0, y0 = line_start
    x1, y1 = line_end
    dx = x1 - x0
    dy = y1 - y0
    denom_sq = dx * dx + dy * dy
    if denom_sq == 0.0:
        return math.hypot(px - x0, py - y0)
    return abs(dy * px - dx * py + x1 * y0 - y1 * x0) / math.sqrt(denom_sq)
