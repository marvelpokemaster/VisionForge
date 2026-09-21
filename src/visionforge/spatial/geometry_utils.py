import numpy as np
from typing import List

# Shared classical-geometry primitives used by both scene_graph.py (P3 graph
# construction) and queries.py (P3 query engine) -- kept in one place so the
# two never compute "distance between two planes" or "is this point inside
# this polygon" in two different, potentially divergent ways.

PARALLEL_DOT_THRESHOLD = 0.85
PERPENDICULAR_DOT_THRESHOLD = 0.25


def segment_segment_distance_3d(p1: np.ndarray, p2: np.ndarray, p3: np.ndarray, p4: np.ndarray) -> float:
    """Minimum distance between 3D segments [p1,p2] and [p3,p4]."""
    EPS = 1e-9
    d1 = p2 - p1
    d2 = p4 - p3
    r = p1 - p3
    a = d1 @ d1
    e = d2 @ d2
    f = d2 @ r

    if a <= EPS and e <= EPS:
        return float(np.linalg.norm(p1 - p3))

    if a <= EPS:
        s = 0.0
        t = np.clip(f / e, 0.0, 1.0)
    else:
        c = d1 @ r
        if e <= EPS:
            t = 0.0
            s = np.clip(-c / a, 0.0, 1.0)
        else:
            b = d1 @ d2
            denom = a * e - b * b
            s = np.clip((b * f - c * e) / denom, 0.0, 1.0) if denom > EPS else 0.0
            t = (b * s + f) / e
            if t < 0.0:
                t = 0.0
                s = np.clip(-c / a, 0.0, 1.0)
            elif t > 1.0:
                t = 1.0
                s = np.clip((b - c) / a, 0.0, 1.0)

    closest1 = p1 + s * d1
    closest2 = p3 + t * d2
    return float(np.linalg.norm(closest1 - closest2))


def polygon_min_distance(hull_a: List[List[float]], hull_b: List[List[float]]) -> float:
    """Minimum distance between two (possibly degenerate) 3D boundary polygons,
    computed edge-to-edge -- correct for convex polygons that only touch or
    approach along a boundary, which is the case for real room surfaces."""
    a = np.array(hull_a, dtype=float)
    b = np.array(hull_b, dtype=float)
    if len(a) == 0 or len(b) == 0:
        return float("inf")

    na, nb = len(a), len(b)
    edges_a = [(a[i], a[(i + 1) % na]) for i in range(na)] if na >= 2 else [(a[0], a[0])]
    edges_b = [(b[i], b[(i + 1) % nb]) for i in range(nb)] if nb >= 2 else [(b[0], b[0])]

    best = float("inf")
    for pa1, pa2 in edges_a:
        for pb1, pb2 in edges_b:
            best = min(best, segment_segment_distance_3d(pa1, pa2, pb1, pb2))
    return best


def point_in_polygon_2d(point: List[float], polygon: List[List[float]]) -> bool:
    """Ray-casting point-in-polygon test (PNPOLY)."""
    x, z = point
    n = len(polygon)
    if n < 3:
        return False
    inside = False
    j = n - 1
    for i in range(n):
        xi, zi = polygon[i]
        xj, zj = polygon[j]
        if (zi > z) != (zj > z):
            x_intersect = (xj - xi) * (z - zi) / (zj - zi + 1e-15) + xi
            if x < x_intersect:
                inside = not inside
        j = i
    return inside


def point_segment_distance_2d(p: np.ndarray, a: np.ndarray, b: np.ndarray) -> float:
    d = b - a
    denom = d @ d
    if denom < 1e-15:
        return float(np.linalg.norm(p - a))
    t = np.clip(((p - a) @ d) / denom, 0.0, 1.0)
    return float(np.linalg.norm(p - (a + t * d)))


def point_polygon_distance_2d(point: List[float], polygon: List[List[float]]) -> float:
    n = len(polygon)
    if n == 0:
        return float("inf")
    p = np.array(point, dtype=float)
    if n == 1:
        return float(np.linalg.norm(p - np.array(polygon[0])))
    best = float("inf")
    for i in range(n):
        a = np.array(polygon[i], dtype=float)
        b = np.array(polygon[(i + 1) % n], dtype=float)
        best = min(best, point_segment_distance_2d(p, a, b))
    return best
