from __future__ import annotations

from dataclasses import dataclass
from math import hypot
from typing import List, Optional, Tuple


@dataclass(frozen=True)
class Pt:
    x: float
    y: float


def dist(a: Pt, b: Pt) -> float:
    return hypot(a.x - b.x, a.y - b.y)


def quant_center(p: Pt, tol: float) -> Tuple[int, int]:
    if tol <= 0:
        return (round(p.x), round(p.y))
    return (int(round(p.x / tol)), int(round(p.y / tol)))


def unique_radii(circles, tol: float) -> List[float]:
    rs = sorted(float(c.dxf.radius) for c in circles)
    uniq: List[float] = []
    for r in rs:
        if not uniq or abs(r - uniq[-1]) > tol:
            uniq.append(r)
    return uniq


def poly_vertices(entity) -> List[Pt]:
    points: List[Pt] = []

    if entity.dxftype() == "LWPOLYLINE":
        for p in entity.get_points():
            points.append(Pt(float(p[0]), float(p[1])))

    elif entity.dxftype() == "POLYLINE":
        for v in entity.vertices:
            loc = v.dxf.location
            points.append(Pt(float(loc.x), float(loc.y)))

    return points


def polygon_center(entity) -> Optional[Pt]:
    points = poly_vertices(entity)
    if not points:
        return None

    return Pt(
        x=sum(p.x for p in points) / len(points),
        y=sum(p.y for p in points) / len(points),
    )


def classify_polygon_shape(entity) -> Optional[str]:
    points = poly_vertices(entity)
    if len(points) < 3:
        return None

    if len(points) >= 2 and dist(points[0], points[-1]) < 1e-6:
        points = points[:-1]

    if len(points) == 3:
        return "triangle"

    if len(points) == 4:
        return "square"

    return None