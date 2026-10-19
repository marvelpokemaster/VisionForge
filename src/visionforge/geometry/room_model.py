import numpy as np
import json
import open3d as o3d
from pathlib import Path
from typing import Dict, Any, List, Optional, Tuple


PERPENDICULAR_DOT_THRESHOLD = 0.25


def _in_plane_axes(
    normal: np.ndarray,
    up_axis: np.ndarray,
    x_axis: np.ndarray,
) -> Tuple[np.ndarray, np.ndarray]:
    """
    Orthonormal basis spanning the plane.

    axis_v is the projection of up_axis onto the plane.
    For near-horizontal planes, where up_axis is parallel to the normal,
    the room x_axis is used instead.
    """
    normal = normal / max(
        np.linalg.norm(normal),
        1e-12,
    )

    v = (
        up_axis
        - np.dot(
            up_axis,
            normal,
        )
        * normal
    )

    if np.linalg.norm(v) < 1e-3:
        v = (
            x_axis
            - np.dot(
                x_axis,
                normal,
            )
            * normal
        )

    v = v / max(
        np.linalg.norm(v),
        1e-12,
    )

    u = np.cross(
        normal,
        v,
    )

    u = u / max(
        np.linalg.norm(u),
        1e-12,
    )

    return u, v


def _convex_hull_2d(
    points: np.ndarray,
) -> np.ndarray:
    """
    Andrew's monotone chain convex hull.

    points: (N,2)
    Returns ordered hull vertices CCW.
    """
    pts = np.asarray(
        points,
        dtype=float,
    )

    if len(pts) == 0:
        return np.zeros(
            (0, 2),
            dtype=float,
        )

    pts = np.unique(
        pts,
        axis=0,
    )

    if len(pts) < 3:
        return pts

    pts = pts[
        np.lexsort(
            (
                pts[:, 1],
                pts[:, 0],
            )
        )
    ]

    def cross(o, a, b):
        return (
            (a[0] - o[0])
            * (b[1] - o[1])
            - (
                a[1] - o[1]
            )
            * (b[0] - o[0])
        )

    lower = []

    for p in pts:
        while (
            len(lower) >= 2
            and cross(
                lower[-2],
                lower[-1],
                p,
            ) <= 0
        ):
            lower.pop()

        lower.append(p)

    upper = []

    for p in reversed(pts):
        while (
            len(upper) >= 2
            and cross(
                upper[-2],
                upper[-1],
                p,
            ) <= 0
        ):
            upper.pop()

        upper.append(p)

    hull = (
        lower[:-1]
        + upper[:-1]
    )

    return np.array(
        hull,
        dtype=float,
    )


def _polygon_area_2d(
    hull: np.ndarray,
) -> float:
    if len(hull) < 3:
        return 0.0

    x = hull[:, 0]
    y = hull[:, 1]

    return float(
        0.5
        * abs(
            np.dot(
                x,
                np.roll(
                    y,
                    -1,
                ),
            )
            - np.dot(
                y,
                np.roll(
                    x,
                    -1,
                ),
            )
        )
    )


def _measurement_axes_from_walls(
    planes: List[Dict[str, Any]],
    up_axis: np.ndarray,
    fallback_x: np.ndarray,
    fallback_z: np.ndarray,
) -> Tuple[np.ndarray, np.ndarray, Dict[str, Any]]:
    """
    Derive stable horizontal measurement axes from detected wall normals.

    Why this exists:
        PCA is not reliable for a square floor because both principal
        directions have equal variance. PCA may therefore select a 45-degree
        direction and measure a 5x5 floor as roughly 7x7.

    Instead, wall normals give us the actual room directions.

    Returns:
        axis_x
        axis_z
        metadata
    """
    up = np.asarray(
        up_axis,
        dtype=float,
    )

    up = up / max(
        np.linalg.norm(up),
        1e-12,
    )

    candidates = []

    for plane in planes:
        if (
            plane.get(
                "classification"
            )
            != "wall"
        ):
            continue

        normal = np.asarray(
            plane.get(
                "normal",
                [],
            ),
            dtype=float,
        )

        norm = np.linalg.norm(
            normal
        )

        if norm < 1e-9:
            continue

        normal = normal / norm

        # Project the wall normal onto the horizontal plane.
        horizontal = (
            normal
            - np.dot(
                normal,
                up,
            )
            * up
        )

        h_norm = np.linalg.norm(
            horizontal
        )

        if h_norm < 1e-6:
            continue

        horizontal = (
            horizontal
            / h_norm
        )

        support = int(
            plane.get(
                "inliers",
                0,
            )
        )

        candidates.append(
            (
                horizontal,
                support,
                plane.get(
                    "id"
                ),
            )
        )

    if not candidates:
        return (
            np.asarray(
                fallback_x,
                dtype=float,
            ),
            np.asarray(
                fallback_z,
                dtype=float,
            ),
            {
                "source": "coordinate_system_fallback",
                "wall_directions_used": [],
            },
        )

    # Strongest wall first.
    candidates.sort(
        key=lambda item: item[1],
        reverse=True,
    )

    first = candidates[0][0]

    second = None

    for candidate, _, _ in candidates[1:]:
        # Wall normals representing the same wall direction can be opposite.
        # We need a genuinely different horizontal direction.
        angle_dot = abs(
            float(
                np.dot(
                    first,
                    candidate,
                )
            )
        )

        if angle_dot < 0.70:
            second = candidate
            break

    if second is None:
        # Only one independent wall direction exists.
        # Construct a perpendicular horizontal axis from the first wall.
        second = np.cross(
            up,
            first,
        )

        second_norm = np.linalg.norm(
            second
        )

        if second_norm < 1e-9:
            return (
                np.asarray(
                    fallback_x,
                    dtype=float,
                ),
                np.asarray(
                    fallback_z,
                    dtype=float,
                ),
                {
                    "source": (
                        "coordinate_system_fallback"
                    ),
                    "wall_directions_used": [],
                },
            )

        second = (
            second
            / second_norm
        )

    # Ensure the two axes are exactly orthogonal.
    axis_x = first

    axis_z = (
        second
        - np.dot(
            second,
            axis_x,
        )
        * axis_x
    )

    axis_z = axis_z / max(
        np.linalg.norm(
            axis_z
        ),
        1e-12,
    )

    # Make the pair right-handed with UP.
    expected_z = np.cross(
        axis_x,
        up,
    )

    if np.dot(
        axis_z,
        expected_z,
    ) < 0:
        axis_z = -axis_z

    return (
        axis_x,
        axis_z,
        {
            "source": "wall_normals",
            "wall_directions_used": [
                item[2]
                for item in candidates
                if item[2] is not None
            ][:2],
        },
    )


def _project_horizontal(
    points: np.ndarray,
    origin: np.ndarray,
    x_axis: np.ndarray,
    z_axis: np.ndarray,
) -> np.ndarray:
    """
    Project 3D points into the room's horizontal coordinate system.
    """
    rel = (
        points
        - origin
    )

    return np.column_stack(
        [
            rel @ x_axis,
            rel @ z_axis,
        ]
    )


def _horizontal_extent(
    points: np.ndarray,
    x_axis: np.ndarray,
    z_axis: np.ndarray,
    robust: bool = False,
) -> Tuple[float, float]:
    """
    Calculate horizontal extents along explicit room axes.

    This is intentionally NOT PCA based.

    Returns:
        extent_x
        extent_z
    """
    if len(points) == 0:
        return 0.0, 0.0

    x_coords = (
        points
        @ x_axis
    )

    z_coords = (
        points
        @ z_axis
    )

    if robust and len(points) >= 20:
        x_min, x_max = np.percentile(
            x_coords,
            [2.0, 98.0],
        )

        z_min, z_max = np.percentile(
            z_coords,
            [2.0, 98.0],
        )

    else:
        x_min = np.min(
            x_coords
        )

        x_max = np.max(
            x_coords
        )

        z_min = np.min(
            z_coords
        )

        z_max = np.max(
            z_coords
        )

    return (
        float(
            x_max - x_min
        ),
        float(
            z_max - z_min
        ),
    )


def _plane_boundary(
    cloud: o3d.geometry.PointCloud,
    centroid: np.ndarray,
    axis_u: np.ndarray,
    axis_v: np.ndarray,
) -> Tuple[np.ndarray, np.ndarray]:
    """
    Convex hull of the plane's inliers projected onto the plane.

    Returns:
        hull_3d
        hull_2d
    """
    pts = np.asarray(
        cloud.points
    )

    if len(pts) == 0:
        return (
            np.zeros(
                (0, 3),
                dtype=float,
            ),
            np.zeros(
                (0, 2),
                dtype=float,
            ),
        )

    rel = (
        pts
        - centroid
    )

    coords_2d = np.column_stack(
        [
            rel @ axis_u,
            rel @ axis_v,
        ]
    )

    hull_2d = _convex_hull_2d(
        coords_2d
    )

    if len(hull_2d) == 0:
        return (
            np.zeros(
                (0, 3),
                dtype=float,
            ),
            hull_2d,
        )

    hull_3d = (
        centroid
        + hull_2d[:, 0:1]
        * axis_u
        + hull_2d[:, 1:2]
        * axis_v
    )

    return (
        hull_3d,
        hull_2d,
    )


def _room_frame_point(
    p: np.ndarray,
    origin: np.ndarray,
    x_axis: np.ndarray,
    up_axis: np.ndarray,
    z_axis: np.ndarray,
) -> List[float]:
    rel = (
        p
        - origin
    )

    return [
        float(
            np.dot(
                rel,
                x_axis,
            )
        ),
        float(
            np.dot(
                rel,
                up_axis,
            )
        ),
        float(
            np.dot(
                rel,
                z_axis,
            )
        ),
    ]


def _room_origin(
    planes: List[Dict[str, Any]],
) -> np.ndarray:
    """
    Use the largest detected floor as the room origin.

    Falls back to the mean plane centroid if no floor exists.
    """
    floors = [
        p
        for p in planes
        if p["classification"]
        == "floor"
    ]

    if floors:
        largest = max(
            floors,
            key=lambda p: p[
                "inliers"
            ],
        )

        return np.array(
            largest["centroid"],
            dtype=float,
        )

    return np.mean(
        [
            p["centroid"]
            for p in planes
        ],
        axis=0,
    )


def _plane_intersection(
    plane_a: Dict[str, Any],
    plane_b: Dict[str, Any],
    boundary_a_3d: np.ndarray,
    boundary_b_3d: np.ndarray,
) -> Optional[Dict[str, Any]]:
    """
    Compute the intersection line of two near-perpendicular planes.

    The line is clipped to their overlapping boundary extents.
    """
    n1 = np.array(
        plane_a["normal"],
        dtype=float,
    )

    d1 = float(
        plane_a[
            "equation"
        ][3]
    )

    n2 = np.array(
        plane_b["normal"],
        dtype=float,
    )

    d2 = float(
        plane_b[
            "equation"
        ][3]
    )

    if (
        abs(
            np.dot(
                n1,
                n2,
            )
        )
        >= PERPENDICULAR_DOT_THRESHOLD
    ):
        return None

    direction = np.cross(
        n1,
        n2,
    )

    norm_dir = np.linalg.norm(
        direction
    )

    if norm_dir < 1e-6:
        return None

    direction = (
        direction
        / norm_dir
    )

    ref_point = (
        np.array(
            plane_a["centroid"],
            dtype=float,
        )
        + np.array(
            plane_b["centroid"],
            dtype=float,
        )
    ) / 2.0

    matrix = np.array(
        [
            n1,
            n2,
            direction,
        ]
    )

    rhs = np.array(
        [
            -d1,
            -d2,
            np.dot(
                direction,
                ref_point,
            ),
        ]
    )

    try:
        point_on_line = (
            np.linalg.solve(
                matrix,
                rhs,
            )
        )

    except np.linalg.LinAlgError:
        return None

    if (
        len(boundary_a_3d) == 0
        or len(boundary_b_3d) == 0
    ):
        return None

    t_a = (
        boundary_a_3d
        - point_on_line
    ) @ direction

    t_b = (
        boundary_b_3d
        - point_on_line
    ) @ direction

    lo = max(
        t_a.min(),
        t_b.min(),
    )

    hi = min(
        t_a.max(),
        t_b.max(),
    )

    if hi <= lo:
        return None

    p_start = (
        point_on_line
        + lo
        * direction
    )

    p_end = (
        point_on_line
        + hi
        * direction
    )

    return {
        "plane_a": plane_a["id"],
        "plane_b": plane_b["id"],
        "point": (
            point_on_line.tolist()
        ),
        "direction": (
            direction.tolist()
        ),
        "segment": [
            p_start.tolist(),
            p_end.tolist(),
        ],
    }


def export_plane_plys(
    planes: List[Dict[str, Any]],
    output_dir: Path,
) -> Dict[str, str]:
    """
    Save each post-merge plane cloud as its own PLY.

    Returns:
        {plane_id: relative_path}
    """
    planes_dir = (
        output_dir
        / "planes"
    )

    planes_dir.mkdir(
        parents=True,
        exist_ok=True,
    )

    ply_paths = {}

    for p in planes:

        filename = (
            f"{p['id']}.ply"
        )

        o3d.io.write_point_cloud(
            str(
                planes_dir
                / filename
            ),
            p["cloud"],
        )

        ply_paths[
            p["id"]
        ] = (
            f"planes/{filename}"
        )

    return ply_paths


def align_and_measure_room(
    planes_data: Dict[str, Any],
    ref_distance: float = None,
    rec_distance: float = None,
    ply_paths: Optional[
        Dict[str, str]
    ] = None,
) -> Dict[str, Any]:

    coord_sys = planes_data.get(
        "coordinate_system"
    )

    planes = planes_data.get(
        "planes",
        [],
    )

    # -----------------------------------------------------------------------
    # Scale calibration
    # -----------------------------------------------------------------------

    scale_factor = 1.0
    metric_available = False

    if (
        ref_distance is not None
        and rec_distance is not None
        and rec_distance > 0
    ):
        scale_factor = (
            ref_distance
            / rec_distance
        )

        metric_available = True

    length = 0.0
    width = 0.0
    height = 0.0
    area = 0.0

    height_method = None
    length_method = None
    width_method = None
    floor_area_method = None

    # -----------------------------------------------------------------------
    # Room measurements
    # -----------------------------------------------------------------------

    measurement_axes_metadata = {
        "source": "unavailable",
        "wall_directions_used": [],
    }

    if coord_sys:

        up = np.array(
            coord_sys[
                "up_axis"
            ],
            dtype=float,
        )

        x_ax = np.array(
            coord_sys[
                "horizontal_axes"
            ][0],
            dtype=float,
        )

        z_ax = np.array(
            coord_sys[
                "horizontal_axes"
            ][1],
            dtype=float,
        )

        # ---------------------------------------------------------------
        # IMPORTANT:
        #
        # Derive measurement directions from wall normals.
        #
        # We do NOT use PCA here because a square floor has equal principal
        # variances and PCA can rotate its axes by 45 degrees.
        # ---------------------------------------------------------------

        (
            measurement_x,
            measurement_z,
            measurement_axes_metadata,
        ) = _measurement_axes_from_walls(
            planes,
            up,
            x_ax,
            z_ax,
        )

        floors = [
            p
            for p in planes
            if p["classification"]
            == "floor"
        ]

        ceilings = [
            p
            for p in planes
            if p["classification"]
            == "ceiling"
        ]

        # ---------------------------------------------------------------
        # Height
        # ---------------------------------------------------------------

        if floors and ceilings:

            f_c = np.array(
                floors[0][
                    "centroid"
                ],
                dtype=float,
            )

            c_c = np.array(
                ceilings[0][
                    "centroid"
                ],
                dtype=float,
            )

            height = (
                abs(
                    np.dot(
                        c_c - f_c,
                        up,
                    )
                )
                * scale_factor
            )

            height_method = (
                "floor_to_ceiling"
            )

        elif floors:

            f_c = np.array(
                floors[0][
                    "centroid"
                ],
                dtype=float,
            )

            max_h = 0.0

            found_wall_points = False

            for p in planes:

                if (
                    p["classification"]
                    == "wall"
                ):

                    pts = np.asarray(
                        p[
                            "cloud"
                        ].points
                    )

                    if len(pts) > 0:

                        found_wall_points = True

                        h = np.max(
                            np.dot(
                                pts - f_c,
                                up,
                            )
                        )

                        max_h = max(
                            max_h,
                            h,
                        )

            height = (
                max_h
                * scale_factor
            )

            if found_wall_points:
                height_method = (
                    "wall_extent_estimate"
                )

        # ---------------------------------------------------------------
        # Floor length / width / area
        # ---------------------------------------------------------------

        if floors:

            floor_pts = np.asarray(
                floors[0][
                    "cloud"
                ].points
            )

            if len(floor_pts) > 0:

                (
                    raw_x_extent,
                    raw_z_extent,
                ) = _horizontal_extent(
                    floor_pts,
                    measurement_x,
                    measurement_z,
                    robust=True,
                )

                # Keep the larger horizontal dimension as length.
                # Keep the smaller as width.
                length_raw = max(
                    raw_x_extent,
                    raw_z_extent,
                )

                width_raw = min(
                    raw_x_extent,
                    raw_z_extent,
                )

                length = (
                    length_raw
                    * scale_factor
                )

                width = (
                    width_raw
                    * scale_factor
                )

                area = (
                    length
                    * width
                )

                # IMPORTANT:
                # Preserve the established method name expected by the
                # existing tests and downstream code.
                length_method = (
                    "floor_extent"
                )

                width_method = (
                    "floor_extent"
                )

                floor_area_method = (
                    "floor_extent"
                )

    # -----------------------------------------------------------------------
    # Plane boundaries / extents / areas
    # -----------------------------------------------------------------------

    boundaries_3d: Dict[
        str,
        np.ndarray,
    ] = {}

    plane_extras: Dict[
        str,
        Dict[str, Any],
    ] = {}

    bounding_polygon_room = []

    intersections = []

    if coord_sys and planes:

        up = np.array(
            coord_sys[
                "up_axis"
            ],
            dtype=float,
        )

        x_ax = np.array(
            coord_sys[
                "horizontal_axes"
            ][0],
            dtype=float,
        )

        z_ax = np.array(
            coord_sys[
                "horizontal_axes"
            ][1],
            dtype=float,
        )

        # Reuse the same wall-derived horizontal axes used by the room
        # measurements.
        (
            measurement_x,
            measurement_z,
            measurement_axes_metadata,
        ) = _measurement_axes_from_walls(
            planes,
            up,
            x_ax,
            z_ax,
        )

        origin = _room_origin(
            planes
        )

        coord_sys[
            "origin"
        ] = origin.tolist()

        coord_sys[
            "measurement_axes"
        ] = {
            "x_axis": (
                measurement_x.tolist()
            ),
            "z_axis": (
                measurement_z.tolist()
            ),
            "source": (
                measurement_axes_metadata[
                    "source"
                ]
            ),
            "wall_directions_used": (
                measurement_axes_metadata[
                    "wall_directions_used"
                ]
            ),
        }

        for p in planes:

            normal = np.array(
                p["normal"],
                dtype=float,
            )

            centroid = np.array(
                p["centroid"],
                dtype=float,
            )

            # -----------------------------------------------------------
            # Floor / ceiling:
            #
            # Use room horizontal measurement axes so their extents reflect
            # the detected room directions rather than an arbitrary basis.
            #
            # Other planes retain their own natural in-plane axes.
            # -----------------------------------------------------------

            if p[
                "classification"
            ] in {
                "floor",
                "ceiling",
            }:

                axis_u = measurement_x
                axis_v = measurement_z

            else:

                (
                    axis_u,
                    axis_v,
                ) = _in_plane_axes(
                    normal,
                    up,
                    x_ax,
                )

            hull_3d, hull_2d = (
                _plane_boundary(
                    p["cloud"],
                    centroid,
                    axis_u,
                    axis_v,
                )
            )

            boundaries_3d[
                p["id"]
            ] = hull_3d

            if len(hull_2d) > 0:

                extent_width = float(
                    hull_2d[:, 0].max()
                    - hull_2d[:, 0].min()
                )

                extent_height = float(
                    hull_2d[:, 1].max()
                    - hull_2d[:, 1].min()
                )

            else:

                extent_width = 0.0
                extent_height = 0.0

            plane_area = (
                _polygon_area_2d(
                    hull_2d
                )
            )

            boundary_room = [
                _room_frame_point(
                    v,
                    origin,
                    x_ax,
                    up,
                    z_ax,
                )
                for v in hull_3d
            ]

            plane_extras[
                p["id"]
            ] = {

                "in_plane_axes": {
                    "axis_u": (
                        axis_u.tolist()
                    ),
                    "axis_v": (
                        axis_v.tolist()
                    ),
                },

                "extent": {
                    "width": (
                        extent_width
                    ),
                    "height": (
                        extent_height
                    ),
                },

                "area": plane_area,

                "boundary": (
                    hull_3d.tolist()
                ),

                "boundary_room": (
                    boundary_room
                ),

                "centroid_room": (
                    _room_frame_point(
                        centroid,
                        origin,
                        x_ax,
                        up,
                        z_ax,
                    )
                ),

                "ply_path": (
                    ply_paths.get(
                        p["id"]
                    )
                    if ply_paths
                    else None
                ),
            }

        # ---------------------------------------------------------------
        # Plane intersections
        # ---------------------------------------------------------------

        for i in range(
            len(planes)
        ):

            for j in range(
                i + 1,
                len(planes),
            ):

                pa = planes[i]
                pb = planes[j]

                result = (
                    _plane_intersection(
                        pa,
                        pb,
                        boundaries_3d[
                            pa["id"]
                        ],
                        boundaries_3d[
                            pb["id"]
                        ],
                    )
                )

                if result:

                    result[
                        "point_room"
                    ] = (
                        _room_frame_point(
                            np.array(
                                result[
                                    "point"
                                ],
                                dtype=float,
                            ),
                            origin,
                            x_ax,
                            up,
                            z_ax,
                        )
                    )

                    result[
                        "segment_room"
                    ] = [

                        _room_frame_point(
                            np.array(
                                v,
                                dtype=float,
                            ),
                            origin,
                            x_ax,
                            up,
                            z_ax,
                        )

                        for v in result[
                            "segment"
                        ]
                    ]

                    intersections.append(
                        result
                    )

        # ---------------------------------------------------------------
        # Room bounding polygon
        # ---------------------------------------------------------------

        all_plane_points = np.concatenate(
            [
                np.asarray(
                    p[
                        "cloud"
                    ].points
                )

                for p in planes

                if len(
                    p[
                        "cloud"
                    ].points
                ) > 0
            ],
            axis=0,
        )

        if len(
            all_plane_points
        ) > 0:

            horiz_2d = (
                _project_horizontal(
                    all_plane_points,
                    origin,
                    measurement_x,
                    measurement_z,
                )
            )

            hull_room_2d = (
                _convex_hull_2d(
                    horiz_2d
                )
            )

            bounding_polygon_room = (
                hull_room_2d
                * scale_factor
            ).tolist()

    # -----------------------------------------------------------------------
    # Output plane records
    # -----------------------------------------------------------------------

    out_planes = []

    for p in planes:

        extras = plane_extras.get(
            p["id"],
            {},
        )

        classification_confidence = (
            p.get(
                "classification_confidence"
            )
        )

        classification_evidence = (
            p.get(
                "classification_evidence"
            )
        )

        out_planes.append(
            {
                "id": p["id"],

                "type": p[
                    "classification"
                ],

                "equation": p[
                    "equation"
                ],

                "normal": p[
                    "normal"
                ],

                "support": p[
                    "inliers"
                ],

                "centroid": p[
                    "centroid"
                ],

                **extras,

                "classification_confidence": (
                    classification_confidence
                ),

                "classification_evidence": (
                    classification_evidence
                ),
            }
        )

    # -----------------------------------------------------------------------
    # Final room model
    # -----------------------------------------------------------------------

    room_model = {

        "coordinate_system": coord_sys,

        "scale": {
            "metric_available": (
                metric_available
            ),

            "scale_factor": (
                scale_factor
            ),
        },

        "room": {

            "length": float(
                length
            ),

            "width": float(
                width
            ),

            "height": float(
                height
            ),

            "floor_area": float(
                area
            ),

            "length_method": (
                length_method
            ),

            "width_method": (
                width_method
            ),

            "height_method": (
                height_method
            ),

            "floor_area_method": (
                floor_area_method
            ),

            "bounding_polygon_room": (
                bounding_polygon_room
            ),
        },

        "planes": out_planes,

        "intersections": intersections,
    }

    return room_model