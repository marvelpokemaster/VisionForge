import numpy as np
import open3d as o3d
from typing import Any, Dict, List, Optional


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

# Maximum angular disagreement between UP sources before they are considered
# inconsistent. Angles are measured between unoriented vector lines.
MAX_SOURCE_AGREEMENT_DEG = 15.0

# Plane normal approximately parallel to UP => horizontal plane.
HORIZONTAL_ANGLE_DEG = 15.0

# Plane normal approximately perpendicular to UP => vertical wall.
WALL_ANGLE_DEG = 15.0

# Minimum plane support as a fraction of the full point cloud.
MIN_PLANE_SUPPORT_RATIO = 0.05

# Minimum fraction of all room points that should be on the UP side of a floor.
MIN_FLOOR_SIDE_RATIO = 0.60

# Minimum relative vertical gap for a ceiling candidate.
CEILING_GAP_FRACTION = 0.15


# ---------------------------------------------------------------------------
# Small geometry helpers
# ---------------------------------------------------------------------------

def _unit(vector: np.ndarray) -> Optional[np.ndarray]:
    """Return a unit vector or None when the input is degenerate."""
    vector = np.asarray(vector, dtype=float).reshape(-1)

    if vector.size != 3:
        return None

    norm = float(np.linalg.norm(vector))

    if norm < 1e-9:
        return None

    return vector / norm


def _normalise_confidence(value: float) -> float:
    """
    Clamp a confidence-like score to [0, 1].

    This is intentionally treated as a bounded reliability score,
    not as a probability.
    """
    return float(np.clip(value, 0.0, 1.0))


def _line_angle_deg(a: np.ndarray, b: np.ndarray) -> float:
    """
    Return the angle between two unoriented vector lines in [0, 90] degrees.

    Using abs(dot) makes +normal and -normal equivalent.
    """
    a_unit = _unit(a)
    b_unit = _unit(b)

    if a_unit is None or b_unit is None:
        return 90.0

    dot = float(np.clip(abs(np.dot(a_unit, b_unit)), -1.0, 1.0))

    return float(np.degrees(np.arccos(dot)))


def _orient_like(vector: np.ndarray, reference: np.ndarray) -> np.ndarray:
    """Flip vector when necessary so it points in the same hemisphere."""
    v = _unit(vector)
    r = _unit(reference)

    if v is None:
        return np.asarray(vector, dtype=float)

    if r is None:
        return v

    if float(np.dot(v, r)) < 0.0:
        return -v

    return v


# ---------------------------------------------------------------------------
# Camera record handling / gravity estimation
# ---------------------------------------------------------------------------

def _camera_records(camera_data: Any):
    """
    Yield camera pose dictionaries from common input structures.

    Supported examples:
        {"rotation_quat": [...]}

        [{"rotation_quat": [...]}, ...]

        {"poses": [{"rotation_quat": [...]}, ...]}

        {"cameras": [{"rotation_quat": [...]}, ...]}

    Also supports a single camera record.
    """
    if camera_data is None:
        return

    if isinstance(camera_data, dict):
        if "rotation_quat" in camera_data:
            yield camera_data
            return

        for key in (
            "cameras",
            "camera_poses",
            "poses",
            "records",
            "frames",
            "camera_records",
        ):
            value = camera_data.get(key)

            if value is None:
                continue

            if isinstance(value, dict):
                for record in _camera_records(value):
                    yield record

            elif isinstance(value, (list, tuple)):
                for record in value:
                    if isinstance(record, dict):
                        yield record

            return

    elif isinstance(camera_data, (list, tuple)):
        for record in camera_data:
            if isinstance(record, dict):
                yield record


def _quat_to_rotation_matrix_xyzw(
    quaternion: Any,
) -> Optional[np.ndarray]:
    """
    Quaternion convention required by the project:

        [x, y, z, w]

    representing cam_from_world.

    The returned matrix is R_cam_from_world.
    """
    q = np.asarray(quaternion, dtype=float).reshape(-1)

    if q.size != 4:
        return None

    norm = float(np.linalg.norm(q))

    if norm < 1e-9:
        return None

    x, y, z, w = q / norm

    return np.array(
        [
            [
                1.0 - 2.0 * (y * y + z * z),
                2.0 * (x * y - z * w),
                2.0 * (x * z + y * w),
            ],
            [
                2.0 * (x * y + z * w),
                1.0 - 2.0 * (x * x + z * z),
                2.0 * (y * z - x * w),
            ],
            [
                2.0 * (x * z - y * w),
                2.0 * (y * z + x * w),
                1.0 - 2.0 * (x * x + y * y),
            ],
        ],
        dtype=float,
    )


def _estimate_camera_gravity(
    camera_data: Any,
) -> Dict[str, Any]:
    """
    Estimate world UP from the phone camera prior.

    rotation_quat is [x,y,z,w] for cam_from_world.

    The camera's local -Y axis in world coordinates is:

        R_cam_from_world.T @ [0,-1,0]
    """
    vectors = []

    for record in _camera_records(camera_data):
        quaternion = record.get("rotation_quat")

        rotation = _quat_to_rotation_matrix_xyzw(quaternion)

        if rotation is None:
            continue

        local_camera_up = np.array(
            [0.0, -1.0, 0.0],
            dtype=float,
        )

        world_up = rotation.T @ local_camera_up
        world_up = _unit(world_up)

        if world_up is not None:
            vectors.append(world_up)

    if not vectors:
        return {
            "vector": None,
            "confidence": 0.0,
            "sample_count": 0,
            "available": False,
            "reason": (
                "No usable rotation_quat camera poses were provided."
            ),
        }

    matrix = np.vstack(vectors)

    mean = np.sum(matrix, axis=0)

    coherence = float(
        np.linalg.norm(mean) / len(vectors)
    )

    if coherence < 1e-6:
        return {
            "vector": None,
            "confidence": 0.0,
            "sample_count": len(vectors),
            "available": False,
            "reason": "Camera gravity vectors cancel out.",
        }

    world_up = mean / np.linalg.norm(mean)

    count_factor = min(
        1.0,
        len(vectors) / 8.0,
    )

    confidence = _normalise_confidence(
        0.75 * coherence
        + 0.25 * count_factor
    )

    return {
        "vector": world_up.tolist(),
        "confidence": confidence,
        "sample_count": len(vectors),
        "available": True,
        "coherence": coherence,
    }


# ---------------------------------------------------------------------------
# Manhattan / architectural UP estimation
# ---------------------------------------------------------------------------

def _estimate_manhattan_normal(
    planes: List[Dict[str, Any]],
) -> Dict[str, Any]:
    """
    Find the dominant unoriented normal direction among near-parallel
    plane pairs.

    The estimator is intentionally scale-independent.
    """
    if len(planes) < 2:
        return {
            "vector": None,
            "confidence": 0.0,
            "pair_count": 0,
            "available": False,
            "reason": "Fewer than two planes are available.",
        }

    cos_limit = float(
        np.cos(
            np.radians(
                MAX_SOURCE_AGREEMENT_DEG
            )
        )
    )

    candidates = []

    total_support = sum(
        max(0, int(p.get("inliers", 0)))
        for p in planes
    )

    if total_support <= 0:
        total_support = 1

    for i, base in enumerate(planes):
        base_normal = _unit(
            np.asarray(
                base.get("normal", []),
                dtype=float,
            )
        )

        if base_normal is None:
            continue

        support_sum = 0.0
        pair_count = 0
        weighted_vectors = []
        cluster_members = []

        for j, other in enumerate(planes):
            if i == j:
                continue

            other_normal = _unit(
                np.asarray(
                    other.get("normal", []),
                    dtype=float,
                )
            )

            if other_normal is None:
                continue

            abs_dot = abs(
                float(
                    np.dot(
                        base_normal,
                        other_normal,
                    )
                )
            )

            if abs_dot < cos_limit:
                continue

            if float(
                np.dot(
                    base_normal,
                    other_normal,
                )
            ) < 0.0:
                aligned = -other_normal
            else:
                aligned = other_normal

            weight = max(
                1.0,
                float(other.get("inliers", 0)),
            )

            weighted_vectors.append(
                (aligned, weight)
            )

            support_sum += weight
            pair_count += 1
            cluster_members.append(j)

        if pair_count == 0:
            continue

        base_weight = max(
            1.0,
            float(base.get("inliers", 0)),
        )

        weighted_vectors.append(
            (base_normal, base_weight)
        )

        fused = np.sum(
            [
                vec * weight
                for vec, weight in weighted_vectors
            ],
            axis=0,
        )

        fused = _unit(fused)

        if fused is None:
            continue

        support_factor = min(
            1.0,
            (support_sum + base_weight)
            / max(
                1.0,
                0.5 * total_support,
            ),
        )

        score = support_factor

        candidates.append(
            {
                "vector": fused,
                "score": float(score),
                "pair_count": pair_count,
                "support_sum": (
                    support_sum + base_weight
                ),
                "members": [
                    i,
                    *cluster_members,
                ],
            }
        )

    if not candidates:
        return {
            "vector": None,
            "confidence": 0.0,
            "pair_count": 0,
            "available": False,
            "reason": (
                "No near-parallel plane pair was found."
            ),
        }

    best = max(
        candidates,
        key=lambda item: item["score"],
    )

    pair_factor = min(
        1.0,
        best["pair_count"] / 3.0,
    )

    confidence = _normalise_confidence(
        0.65 * best["score"]
        + 0.35 * pair_factor
    )

    return {
        "vector": best["vector"].tolist(),
        "confidence": confidence,
        "pair_count": int(
            best["pair_count"]
        ),
        "available": True,
        "support_sum": float(
            best["support_sum"]
        ),
        "member_indices": [
            int(v)
            for v in best["members"]
        ],
    }


def _estimate_legacy_normal(
    planes: List[Dict[str, Any]],
) -> Dict[str, Any]:
    """
    Legacy fallback based on the strongest plane.
    """
    if not planes:
        return {
            "vector": None,
            "confidence": 0.0,
            "available": False,
            "reason": "No planes are available.",
        }

    largest = max(
        planes,
        key=lambda p: int(
            p.get("inliers", 0)
        ),
    )

    normal = _unit(
        np.asarray(
            largest.get("normal", []),
            dtype=float,
        )
    )

    if normal is None:
        return {
            "vector": None,
            "confidence": 0.0,
            "available": False,
            "reason": (
                "Largest plane has an invalid normal."
            ),
        }

    total_support = max(
        1,
        sum(
            max(
                0,
                int(
                    p.get("inliers", 0)
                ),
            )
            for p in planes
        ),
    )

    support_share = min(
        1.0,
        float(
            largest.get("inliers", 0)
        ) / total_support,
    )

    confidence = _normalise_confidence(
        0.35
        + 0.65 * support_share
    )

    return {
        "vector": normal.tolist(),
        "confidence": confidence,
        "available": True,
        "plane_id": largest["id"],
        "support_share": support_share,
    }


def _architecture_score(
    up_axis: np.ndarray,
    planes: List[Dict[str, Any]],
    all_points: np.ndarray,
) -> float:
    """
    Score a candidate UP direction using geometry.

    Rewards:
      - horizontal architectural surfaces,
      - meaningful vertical separation,
      - vertical wall structure,
      - scene points lying above a low horizontal surface.
    """
    up = _unit(up_axis)

    if up is None or len(all_points) == 0:
        return 0.0

    projections = all_points @ up

    vertical_extent = float(
        np.max(projections)
        - np.min(projections)
    )

    if vertical_extent < 1e-9:
        return 0.0

    horizontal = []
    vertical = []

    for p in planes:
        n = _unit(
            np.asarray(
                p.get("normal", []),
                dtype=float,
            )
        )

        if n is None:
            continue

        h_angle = _line_angle_deg(
            n,
            up,
        )

        support = float(
            max(
                0,
                p.get("inliers", 0),
            )
        )

        if h_angle <= HORIZONTAL_ANGLE_DEG:
            coord = float(
                np.dot(
                    np.asarray(
                        p["centroid"],
                        dtype=float,
                    ),
                    up,
                )
            )

            horizontal.append(
                (
                    coord,
                    p,
                    support,
                )
            )

        elif abs(
            90.0 - h_angle
        ) <= WALL_ANGLE_DEG:
            vertical.append(
                (
                    p,
                    support,
                )
            )

    if not horizontal:
        return min(
            0.25,
            len(vertical) / 8.0,
        )

    horizontal.sort(
        key=lambda item: item[0]
    )

    low_coord, low_plane, low_support = (
        horizontal[0]
    )

    low_centroid = np.asarray(
        low_plane["centroid"],
        dtype=float,
    )

    signed = (
        all_points - low_centroid
    ) @ up

    above_ratio = float(
        np.mean(
            signed
            >= -0.02
            * vertical_extent
        )
    )

    floor_side_score = np.clip(
        (
            above_ratio - 0.5
        )
        / max(
            1e-6,
            0.95 - 0.5,
        ),
        0.0,
        1.0,
    )

    pair_score = 0.0

    if len(horizontal) >= 2:
        gap = (
            horizontal[-1][0]
            - horizontal[0][0]
        )

        pair_score = np.clip(
            gap
            / max(
                1e-9,
                0.5 * vertical_extent,
            ),
            0.0,
            1.0,
        )

    wall_score = np.clip(
        len(vertical) / 4.0,
        0.0,
        1.0,
    )

    horizontal_support = sum(
        item[2]
        for item in horizontal
    )

    support_score = np.clip(
        low_support
        / max(
            1.0,
            horizontal_support,
        ),
        0.0,
        1.0,
    )

    return float(
        0.45 * floor_side_score
        + 0.30 * pair_score
        + 0.15 * wall_score
        + 0.10 * support_score
    )


def _fuse_up_sources(
    source_results: Dict[str, Dict[str, Any]],
    planes: List[Dict[str, Any]],
    all_points: np.ndarray,
) -> Dict[str, Any]:
    """
    Fuse the available UP sources using confidence plus angular agreement.

    Sources can be:
      - camera gravity,
      - Manhattan plane normals,
      - legacy strongest-plane normal.
    """
    available = []

    for name, result in source_results.items():
        if (
            not result.get("available")
            or result.get("vector") is None
        ):
            continue

        vector = _unit(
            np.asarray(
                result["vector"],
                dtype=float,
            )
        )

        if (
            vector is not None
            and result.get(
                "confidence",
                0.0,
            ) > 0.0
        ):
            available.append(
                (
                    name,
                    vector,
                    float(
                        result["confidence"]
                    ),
                )
            )

    if not available:
        candidate_vectors = [
            _unit(
                np.asarray(
                    p["normal"],
                    dtype=float,
                )
            )
            for p in planes
        ]

        candidate_vectors = [
            v
            for v in candidate_vectors
            if v is not None
        ]

        if not candidate_vectors:
            return {
                "up_vector": None,
                "confidence": 0.0,
                "up_source": "unavailable",
                "agreed_sources": [],
                "disagreed_sources": [],
            }

        best = max(
            candidate_vectors,
            key=lambda v: _architecture_score(
                v,
                planes,
                all_points,
            ),
        )

        best_score = _architecture_score(
            best,
            planes,
            all_points,
        )

        return {
            "up_vector": best.tolist(),
            "confidence": _normalise_confidence(
                0.25
                + 0.5 * best_score
            ),
            "up_source": "architecture_fallback",
            "agreed_sources": [],
            "disagreed_sources": list(
                source_results.keys()
            ),
        }

    clusters = []

    for name, vector, confidence in available:
        members = []

        for (
            other_name,
            other_vector,
            other_confidence,
        ) in available:
            angle = _line_angle_deg(
                vector,
                other_vector,
            )

            if angle <= MAX_SOURCE_AGREEMENT_DEG:
                aligned = _orient_like(
                    other_vector,
                    vector,
                )

                members.append(
                    (
                        other_name,
                        aligned,
                        other_confidence,
                    )
                )

        weighted = np.sum(
            [
                v * c
                for _, v, c in members
            ],
            axis=0,
        )

        fused = _unit(weighted)

        if fused is None:
            continue

        source_weight = sum(
            c
            for _, _, c in members
        )

        agreement_fraction = (
            len(members)
            / max(
                1,
                len(available),
            )
        )

        architecture = _architecture_score(
            fused,
            planes,
            all_points,
        )

        score = (
            source_weight
            * (
                0.75
                + 0.25
                * agreement_fraction
            )
            + 0.75
            * architecture
        )

        clusters.append(
            {
                "vector": fused,
                "score": float(score),
                "members": [
                    m[0]
                    for m in members
                ],
                "member_confidences": {
                    m[0]: float(m[2])
                    for m in members
                },
                "architecture_score": architecture,
            }
        )

    if not clusters:
        return {
            "up_vector": None,
            "confidence": 0.0,
            "up_source": "unavailable",
            "agreed_sources": [],
            "disagreed_sources": list(
                source_results.keys()
            ),
        }

    best = max(
        clusters,
        key=lambda item: item["score"],
    )

    final_vector = best["vector"]

    available_names = {
        name
        for name, _, _ in available
    }

    agreed = best["members"]

    disagreed = sorted(
        available_names.difference(
            agreed
        )
    )

    total_conf = sum(
        conf
        for _, _, conf in available
    )

    agreement_conf = sum(
        best["member_confidences"].values()
    )

    agreement_ratio = (
        agreement_conf
        / max(
            1e-9,
            total_conf,
        )
    )

    final_confidence = _normalise_confidence(
        0.60 * agreement_ratio
        + 0.25
        * min(
            1.0,
            len(agreed) / 3.0,
        )
        + 0.15
        * best["architecture_score"]
    )

    if len(agreed) == 1:
        up_source = agreed[0]
    else:
        up_source = "+".join(agreed)

    return {
        "up_vector": final_vector.tolist(),
        "confidence": final_confidence,
        "up_source": up_source,
        "agreed_sources": agreed,
        "disagreed_sources": disagreed,
        "architecture_score": float(
            best["architecture_score"]
        ),
    }


# ---------------------------------------------------------------------------
# Floor / ceiling / wall candidate identification
# ---------------------------------------------------------------------------

def _has_two_wall_directions(
    planes: List[Dict[str, Any]],
    up: np.ndarray,
    all_points_count: int,
) -> bool:
    """
    Check whether the scene contains at least two independent wall-normal
    directions.

    This is retained as architectural evidence, but it is NOT a hard
    requirement for floor classification.
    """
    wall_dirs = []

    min_support = MIN_PLANE_SUPPORT_RATIO

    for p in planes:
        normal = _unit(
            np.asarray(
                p.get("normal", []),
                dtype=float,
            )
        )

        if normal is None:
            continue

        support_ratio = (
            float(
                p.get(
                    "inliers",
                    0,
                )
            )
            / max(
                1,
                all_points_count,
            )
        )

        if support_ratio < min_support:
            continue

        horizontal_angle = _line_angle_deg(
            normal,
            up,
        )

        if abs(
            90.0 - horizontal_angle
        ) > WALL_ANGLE_DEG:
            continue

        already_seen = False

        for existing in wall_dirs:
            if (
                _line_angle_deg(
                    normal,
                    existing,
                )
                <= MAX_SOURCE_AGREEMENT_DEG
            ):
                already_seen = True
                break

        if not already_seen:
            wall_dirs.append(normal)

    return len(wall_dirs) >= 2


def _find_floor_candidate(
    planes: List[Dict[str, Any]],
    up: np.ndarray,
    all_points: np.ndarray,
    vertical_extent: float,
) -> Optional[Dict[str, Any]]:
    """
    Find the most plausible floor plane.

    Requirements:
      - approximately horizontal,
      - sufficiently supported,
      - most room points lie on its UP side.

    IMPORTANT TASK-1 CHANGE:
    A floor is no longer rejected simply because two independent wall
    directions are unavailable.

    This allows valid partial reconstructions such as:
        floor + one wall
        floor + ceiling
        floor + multiple walls
    """
    horizontal = []

    total_points = max(
        1,
        len(all_points),
    )

    support_ratio_threshold = (
        MIN_PLANE_SUPPORT_RATIO
    )

    for p in planes:
        normal = _unit(
            np.asarray(
                p["normal"],
                dtype=float,
            )
        )

        if normal is None:
            continue

        angle = _line_angle_deg(
            normal,
            up,
        )

        support_ratio = (
            float(
                p.get(
                    "inliers",
                    0,
                )
            )
            / total_points
        )

        if angle > HORIZONTAL_ANGLE_DEG:
            continue

        if (
            support_ratio
            < support_ratio_threshold
        ):
            continue

        centroid = np.asarray(
            p["centroid"],
            dtype=float,
        )

        signed = (
            all_points
            - centroid
        ) @ up

        tolerance = max(
            1e-9,
            0.02
            * vertical_extent,
        )

        above_ratio = float(
            np.mean(
                signed
                >= -tolerance
            )
        )

        horizontal.append(
            {
                "plane": p,
                "height": float(
                    np.dot(
                        centroid,
                        up,
                    )
                ),
                "angle_deg": angle,
                "support_ratio": support_ratio,
                "above_ratio": above_ratio,
            }
        )

    if not horizontal:
        return None

    horizontal.sort(
        key=lambda item: item["height"]
    )

    candidate = horizontal[0]

    if (
        candidate["above_ratio"]
        < MIN_FLOOR_SIDE_RATIO
    ):
        return None

    # ---------------------------------------------------------------
    # TASK-1 EDIT:
    #
    # Previously the function rejected the floor unless the scene
    # contained two independent wall directions.
    #
    # We still calculate that architectural evidence, but we use it
    # as metadata instead of making it a mandatory condition.
    # ---------------------------------------------------------------

    has_two_walls = _has_two_wall_directions(
        planes,
        up,
        len(all_points),
    )

    # Check whether another horizontal plane provides evidence of
    # a floor/ceiling architectural pair.
    has_ceiling_pair = False

    for other in horizontal[1:]:
        gap = (
            other["height"]
            - candidate["height"]
        )

        gap_fraction = (
            gap
            / max(
                vertical_extent,
                1e-9,
            )
        )

        if (
            gap_fraction
            > CEILING_GAP_FRACTION
        ):
            has_ceiling_pair = True
            break

    candidate["vertical_gap_fraction"] = 0.0

    candidate["architectural_support"] = {
        "two_wall_directions": (
            has_two_walls
        ),
        "ceiling_pair": (
            has_ceiling_pair
        ),
    }

    return candidate


def _find_ceiling_candidate(
    planes: List[Dict[str, Any]],
    floor_candidate: Dict[str, Any],
    up: np.ndarray,
    vertical_extent: float,
    all_points: np.ndarray,
) -> Optional[Dict[str, Any]]:
    """
    Find a plausible ceiling above the detected floor.
    """
    floor_height = (
        floor_candidate["height"]
    )

    total_points = max(
        1,
        len(all_points),
    )

    candidates = []

    for p in planes:
        if (
            p["id"]
            == floor_candidate["plane"]["id"]
        ):
            continue

        normal = _unit(
            np.asarray(
                p["normal"],
                dtype=float,
            )
        )

        if normal is None:
            continue

        angle = _line_angle_deg(
            normal,
            up,
        )

        support_ratio = (
            float(
                p.get(
                    "inliers",
                    0,
                )
            )
            / total_points
        )

        if angle > HORIZONTAL_ANGLE_DEG:
            continue

        if (
            support_ratio
            < MIN_PLANE_SUPPORT_RATIO
        ):
            continue

        centroid = np.asarray(
            p["centroid"],
            dtype=float,
        )

        height = float(
            np.dot(
                centroid,
                up,
            )
        )

        gap = height - floor_height

        gap_fraction = (
            gap
            / max(
                vertical_extent,
                1e-9,
            )
        )

        if (
            gap_fraction
            <= CEILING_GAP_FRACTION
        ):
            continue

        signed = (
            all_points
            - centroid
        ) @ up

        tolerance = max(
            1e-9,
            0.02
            * vertical_extent,
        )

        below_ratio = float(
            np.mean(
                signed
                <= tolerance
            )
        )

        candidates.append(
            {
                "plane": p,
                "height": height,
                "angle_deg": angle,
                "support_ratio": support_ratio,
                "gap_fraction": gap_fraction,
                "below_ratio": below_ratio,
            }
        )

    if not candidates:
        return None

    candidates.sort(
        key=lambda item: item["height"],
        reverse=True,
    )

    return candidates[0]


# ---------------------------------------------------------------------------
# Classification confidence
# ---------------------------------------------------------------------------

def _class_confidence(
    support_ratio: float,
    orientation_score: float,
    positional_score: float,
    architectural_score: float = 0.0,
) -> float:
    return _normalise_confidence(
        0.30
        * np.clip(
            support_ratio / 0.30,
            0.0,
            1.0,
        )
        + 0.30
        * orientation_score
        + 0.25
        * positional_score
        + 0.15
        * architectural_score
    )


# ---------------------------------------------------------------------------
# RANSAC plane extraction
# ---------------------------------------------------------------------------

def extract_dominant_planes(
    pcd: o3d.geometry.PointCloud,
    distance_threshold: float = 0.05,
    ransac_n: int = 3,
    num_iterations: int = 1000,
    min_ratio: float = 0.05,
    max_planes: int = 10,
) -> List[Dict[str, Any]]:
    """
    Iteratively extract dominant RANSAC planes.
    """
    planes = []

    remaining_pcd = pcd

    initial_points = len(
        pcd.points
    )

    for i in range(max_planes):
        if (
            len(remaining_pcd.points)
            < initial_points * min_ratio
        ):
            break

        plane_model, inliers = (
            remaining_pcd.segment_plane(
                distance_threshold=distance_threshold,
                ransac_n=ransac_n,
                num_iterations=num_iterations,
            )
        )

        if (
            len(inliers)
            < initial_points * min_ratio
        ):
            break

        inlier_cloud = (
            remaining_pcd.select_by_index(
                inliers
            )
        )

        a, b, c, d = plane_model

        normal = np.array(
            [a, b, c],
            dtype=float,
        )

        normal = normal / max(
            np.linalg.norm(normal),
            1e-12,
        )

        centroid = (
            inlier_cloud.get_center()
        )

        planes.append(
            {
                "id": f"plane_{i:03d}",
                "equation": [
                    float(a),
                    float(b),
                    float(c),
                    float(d),
                ],
                "normal": normal.tolist(),
                "inliers": len(inliers),
                "inlier_ratio": (
                    len(inliers)
                    / initial_points
                ),
                "centroid": centroid.tolist(),
                "cloud": inlier_cloud,
            }
        )

        remaining_pcd = (
            remaining_pcd.select_by_index(
                inliers,
                invert=True,
            )
        )

    return planes


# ---------------------------------------------------------------------------
# Coplanar-plane merging
# ---------------------------------------------------------------------------

def merge_coplanar_planes(
    planes: List[Dict[str, Any]],
    distance_threshold: float,
    normal_dot_threshold: float = 0.98,
    offset_factor: float = 2.0,
) -> List[Dict[str, Any]]:
    """
    Merge RANSAC plane segments that belong to the same physical plane.

    Conditions:
      - normals agree,
      - plane offsets are close,
      - inlier clouds are combined.
    """
    used = [False] * len(planes)

    merged = []

    for i in range(len(planes)):
        if used[i]:
            continue

        used[i] = True

        base = dict(
            planes[i]
        )

        base_normal = np.array(
            base["normal"],
            dtype=float,
        )

        base_d = float(
            base["equation"][3]
        )

        combined_cloud = base["cloud"]

        combined_inliers = int(
            base["inliers"]
        )

        combined_ratio = float(
            base.get(
                "inlier_ratio",
                0.0,
            )
        )

        for j in range(
            i + 1,
            len(planes),
        ):
            if used[j]:
                continue

            other = planes[j]

            other_normal = np.array(
                other["normal"],
                dtype=float,
            )

            other_d = float(
                other["equation"][3]
            )

            dot = float(
                np.dot(
                    base_normal,
                    other_normal,
                )
            )

            if (
                abs(dot)
                <= normal_dot_threshold
            ):
                continue

            other_d_aligned = (
                other_d
                if dot > 0
                else -other_d
            )

            if (
                abs(
                    base_d
                    - other_d_aligned
                )
                >= (
                    offset_factor
                    * distance_threshold
                )
            ):
                continue

            used[j] = True

            combined_cloud = (
                combined_cloud
                + other["cloud"]
            )

            combined_inliers += int(
                other["inliers"]
            )

            combined_ratio += float(
                other.get(
                    "inlier_ratio",
                    0.0,
                )
            )

        base["cloud"] = (
            combined_cloud
        )

        base["inliers"] = (
            combined_inliers
        )

        base["inlier_ratio"] = (
            combined_ratio
        )

        base["centroid"] = (
            combined_cloud
            .get_center()
            .tolist()
        )

        merged.append(base)

    return merged


# ---------------------------------------------------------------------------
# Final plane classification
# ---------------------------------------------------------------------------

def classify_planes(
    planes: List[Dict[str, Any]],
    all_points: np.ndarray,
    camera_data: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """
    Architectural plane classification.

    UP sources:
      1. Camera gravity prior.
      2. Dominant near-parallel plane-normal direction.
      3. Largest-plane legacy fallback.

    Sources are fused using confidence and angular agreement.

    Plane classes:
      - floor
      - ceiling
      - wall
      - unknown
    """
    if not planes:
        return {
            "coordinate_system": None,
            "planes": [],
        }

    all_points = np.asarray(
        all_points,
        dtype=float,
    )

    if (
        all_points.ndim != 2
        or all_points.shape[1] != 3
        or len(all_points) == 0
    ):
        raise ValueError(
            "all_points must be a "
            "non-empty (N, 3) array."
        )

    source_results = {
        "camera_gravity": (
            _estimate_camera_gravity(
                camera_data
            )
        ),
        "manhattan_planes": (
            _estimate_manhattan_normal(
                planes
            )
        ),
        "largest_plane_legacy": (
            _estimate_legacy_normal(
                planes
            )
        ),
    }

    fused = _fuse_up_sources(
        source_results,
        planes,
        all_points,
    )

    if fused["up_vector"] is None:
        return {
            "coordinate_system": None,
            "planes": planes,
        }

    up = _unit(
        np.asarray(
            fused["up_vector"],
            dtype=float,
        )
    )

    if up is None:
        return {
            "coordinate_system": None,
            "planes": planes,
        }

    # -----------------------------------------------------------------------
    # TASK-1 robustness edit:
    #
    # Evaluate both possible UP orientations. Plane normals have no inherent
    # sign, so +UP and -UP can otherwise swap floor and ceiling.
    # -----------------------------------------------------------------------

    vertical_extent = float(
        np.ptp(
            all_points @ up
        )
    )

    floor_candidate_positive = (
        _find_floor_candidate(
            planes,
            up,
            all_points,
            vertical_extent,
        )
    )

    floor_candidate_negative = (
        _find_floor_candidate(
            planes,
            -up,
            all_points,
            vertical_extent,
        )
    )

    if (
        floor_candidate_positive is not None
        and floor_candidate_negative is None
    ):
        pass

    elif (
        floor_candidate_positive is None
        and floor_candidate_negative is not None
    ):
        up = -up

    elif (
        floor_candidate_positive is not None
        and floor_candidate_negative is not None
    ):
        positive_score = (
            _architecture_score(
                up,
                planes,
                all_points,
            )
        )

        negative_score = (
            _architecture_score(
                -up,
                planes,
                all_points,
            )
        )

        if negative_score > positive_score:
            up = -up

    # Recompute everything after final UP orientation.
    vertical_extent = float(
        np.ptp(
            all_points @ up
        )
    )

    floor_candidate = (
        _find_floor_candidate(
            planes,
            up,
            all_points,
            vertical_extent,
        )
    )

    ceiling_candidate = None

    if floor_candidate is not None:
        ceiling_candidate = (
            _find_ceiling_candidate(
                planes,
                floor_candidate,
                up,
                vertical_extent,
                all_points,
            )
        )

    floor_id = (
        floor_candidate["plane"]["id"]
        if floor_candidate is not None
        else None
    )

    ceiling_id = (
        ceiling_candidate["plane"]["id"]
        if ceiling_candidate is not None
        else None
    )

    # -----------------------------------------------------------------------
    # Initialize invalid normals as unknown.
    # -----------------------------------------------------------------------

    for p in planes:
        n = _unit(
            np.asarray(
                p.get("normal", []),
                dtype=float,
            )
        )

        if n is None:
            p["classification"] = "unknown"

            p[
                "classification_confidence"
            ] = 0.0

            p[
                "classification_evidence"
            ] = {
                "reason": (
                    "Invalid plane normal."
                )
            }

    # -----------------------------------------------------------------------
    # Explicit floor / ceiling labels.
    # -----------------------------------------------------------------------

    if floor_id is not None:
        floor_plane = (
            floor_candidate["plane"]
        )

        floor_plane[
            "classification"
        ] = "floor"

    if ceiling_id is not None:
        ceiling_plane = (
            ceiling_candidate["plane"]
        )

        ceiling_plane[
            "classification"
        ] = "ceiling"

    # -----------------------------------------------------------------------
    # Preliminary wall candidates.
    # -----------------------------------------------------------------------

    horizontal_plane_ids = {
        p["id"]
        for p in planes
        if _line_angle_deg(
            np.asarray(
                p["normal"],
                dtype=float,
            ),
            up,
        )
        <= HORIZONTAL_ANGLE_DEG
    }

    wall_candidates = [
        p
        for p in planes
        if p["id"]
        not in horizontal_plane_ids
        and abs(
            90.0
            - _line_angle_deg(
                np.asarray(
                    p["normal"],
                    dtype=float,
                ),
                up,
            )
        )
        <= WALL_ANGLE_DEG
    ]

    # -----------------------------------------------------------------------
    # Classify all remaining planes.
    # -----------------------------------------------------------------------

    for p in planes:
        n = _unit(
            np.asarray(
                p.get(
                    "normal",
                    [],
                ),
                dtype=float,
            )
        )

        if n is None:
            continue

        support_ratio = (
            float(
                p.get(
                    "inliers",
                    0,
                )
            )
            / max(
                1,
                len(all_points),
            )
        )

        horizontal_angle = (
            _line_angle_deg(
                n,
                up,
            )
        )

        vertical_angle_error = abs(
            90.0
            - horizontal_angle
        )

        centroid = np.asarray(
            p["centroid"],
            dtype=float,
        )

        height = float(
            np.dot(
                centroid,
                up,
            )
        )

        # ---------------------------------------------------------------
        # FLOOR
        # ---------------------------------------------------------------

        if p["id"] == floor_id:
            signed = (
                all_points
                - centroid
            ) @ up

            above_ratio = float(
                np.mean(
                    signed
                    >= -0.02
                    * max(
                        vertical_extent,
                        1e-9,
                    )
                )
            )

            orientation_score = np.clip(
                1.0
                - horizontal_angle
                / HORIZONTAL_ANGLE_DEG,
                0.0,
                1.0,
            )

            positional_score = np.clip(
                0.5
                + 0.5
                * (
                    above_ratio
                    - MIN_FLOOR_SIDE_RATIO
                )
                / 0.4,
                0.0,
                1.0,
            )

            architectural_score = (
                _architecture_score(
                    up,
                    planes,
                    all_points,
                )
            )

            confidence = (
                _class_confidence(
                    support_ratio,
                    orientation_score,
                    positional_score,
                    architectural_score,
                )
            )

            p[
                "classification_confidence"
            ] = confidence

            p[
                "classification_evidence"
            ] = {
                "orientation": {
                    "angle_to_up_deg": (
                        horizontal_angle
                    ),
                    "horizontal_tolerance_deg": (
                        HORIZONTAL_ANGLE_DEG
                    ),
                    "orientation_score": float(
                        orientation_score
                    ),
                },
                "height": {
                    "height_along_up": height,
                    "vertical_extent": (
                        vertical_extent
                    ),
                    "relative_height": 0.0,
                },
                "support": {
                    "support_ratio": (
                        support_ratio
                    ),
                    "minimum_support_ratio": (
                        MIN_PLANE_SUPPORT_RATIO
                    ),
                },
                "room_side": {
                    "points_above_ratio": (
                        above_ratio
                    ),
                    "minimum_above_ratio": (
                        MIN_FLOOR_SIDE_RATIO
                    ),
                },
                "architectural_support": (
                    p.get(
                        "architectural_support"
                    )
                ),
                "reason": (
                    "Lowest supported "
                    "horizontal plane with "
                    "room points predominantly "
                    "above it."
                ),
            }

            continue

        # ---------------------------------------------------------------
        # CEILING
        # ---------------------------------------------------------------

        if p["id"] == ceiling_id:
            signed = (
                all_points
                - centroid
            ) @ up

            below_ratio = float(
                np.mean(
                    signed
                    <= 0.02
                    * max(
                        vertical_extent,
                        1e-9,
                    )
                )
            )

            gap = (
                height
                - floor_candidate["height"]
            )

            gap_fraction = (
                gap
                / max(
                    vertical_extent,
                    1e-9,
                )
            )

            orientation_score = np.clip(
                1.0
                - horizontal_angle
                / HORIZONTAL_ANGLE_DEG,
                0.0,
                1.0,
            )

            positional_score = np.clip(
                (
                    gap_fraction
                    - CEILING_GAP_FRACTION
                )
                / max(
                    1e-6,
                    1.0
                    - CEILING_GAP_FRACTION,
                ),
                0.0,
                1.0,
            )

            architectural_score = (
                _architecture_score(
                    up,
                    planes,
                    all_points,
                )
            )

            confidence = (
                _class_confidence(
                    support_ratio,
                    orientation_score,
                    positional_score,
                    architectural_score,
                )
            )

            p[
                "classification_confidence"
            ] = confidence

            p[
                "classification_evidence"
            ] = {
                "orientation": {
                    "angle_to_up_deg": (
                        horizontal_angle
                    ),
                    "horizontal_tolerance_deg": (
                        HORIZONTAL_ANGLE_DEG
                    ),
                    "orientation_score": float(
                        orientation_score
                    ),
                },
                "height": {
                    "height_along_up": height,
                    "vertical_extent": (
                        vertical_extent
                    ),
                    "relative_height": (
                        float(
                            gap_fraction
                        )
                    ),
                    "minimum_gap_fraction": (
                        CEILING_GAP_FRACTION
                    ),
                },
                "support": {
                    "support_ratio": (
                        support_ratio
                    ),
                    "minimum_support_ratio": (
                        MIN_PLANE_SUPPORT_RATIO
                    ),
                },
                "room_side": {
                    "points_below_ratio": (
                        below_ratio
                    ),
                },
                "reason": (
                    "Supported horizontal "
                    "plane sufficiently "
                    "above the detected floor."
                ),
            }

            continue

        # ---------------------------------------------------------------
        # WALL
        # ---------------------------------------------------------------

        if (
            abs(
                90.0
                - horizontal_angle
            )
            <= WALL_ANGLE_DEG
        ):
            orientation_score = np.clip(
                1.0
                - vertical_angle_error
                / WALL_ANGLE_DEG,
                0.0,
                1.0,
            )

            support_score = np.clip(
                support_ratio / 0.20,
                0.0,
                1.0,
            )

            wall_architecture = 0.0

            if floor_candidate is not None:
                wall_architecture = np.clip(
                    _architecture_score(
                        up,
                        planes,
                        all_points,
                    )
                    + 0.25,
                    0.0,
                    1.0,
                )

            confidence = (
                _normalise_confidence(
                    0.55
                    * orientation_score
                    + 0.30
                    * support_score
                    + 0.15
                    * wall_architecture
                )
            )

            p["classification"] = "wall"

            p[
                "classification_confidence"
            ] = confidence

            p[
                "classification_evidence"
            ] = {
                "orientation": {
                    "angle_to_up_deg": (
                        horizontal_angle
                    ),
                    "vertical_normal_tolerance_deg": (
                        WALL_ANGLE_DEG
                    ),
                    "verticality_error_deg": (
                        vertical_angle_error
                    ),
                    "orientation_score": float(
                        orientation_score
                    ),
                },
                "height": {
                    "height_along_up": height,
                    "vertical_extent": (
                        vertical_extent
                    ),
                },
                "support": {
                    "support_ratio": (
                        support_ratio
                    ),
                    "support_score": float(
                        support_score
                    ),
                },
                "reason": (
                    "Plane normal is "
                    "within the configured "
                    "vertical-normal tolerance."
                ),
            }

        # ---------------------------------------------------------------
        # UNKNOWN
        # ---------------------------------------------------------------

        else:
            p["classification"] = "unknown"

            orientation_score = np.clip(
                1.0
                - min(
                    horizontal_angle,
                    vertical_angle_error,
                )
                / 45.0,
                0.0,
                1.0,
            )

            confidence = (
                _normalise_confidence(
                    0.4
                    * np.clip(
                        support_ratio
                        / 0.20,
                        0.0,
                        1.0,
                    )
                    + 0.2
                    * orientation_score
                )
            )

            p[
                "classification_confidence"
            ] = confidence

            p[
                "classification_evidence"
            ] = {
                "orientation": {
                    "angle_to_up_deg": (
                        horizontal_angle
                    ),
                    "vertical_normal_error_deg": (
                        vertical_angle_error
                    ),
                    "horizontal_tolerance_deg": (
                        HORIZONTAL_ANGLE_DEG
                    ),
                    "vertical_tolerance_deg": (
                        WALL_ANGLE_DEG
                    ),
                },
                "height": {
                    "height_along_up": height,
                    "vertical_extent": (
                        vertical_extent
                    ),
                },
                "support": {
                    "support_ratio": (
                        support_ratio
                    ),
                },
                "reason": (
                    "Plane does not satisfy "
                    "floor, ceiling, or wall "
                    "architectural constraints."
                ),
            }

    # -----------------------------------------------------------------------
    # Build room coordinate axes from the strongest wall normal.
    # -----------------------------------------------------------------------

    x_axis = None

    if wall_candidates:
        wall_candidates = sorted(
            wall_candidates,
            key=lambda p: int(
                p.get(
                    "inliers",
                    0,
                )
            ),
            reverse=True,
        )

        n = _unit(
            np.asarray(
                wall_candidates[0]["normal"],
                dtype=float,
            )
        )

        if n is not None:
            projected = (
                n
                - np.dot(n, up)
                * up
            )

            x_axis = _unit(
                projected
            )

    if x_axis is None:
        # Deterministic fallback basis.
        fallback = np.array(
            [1.0, 0.0, 0.0],
            dtype=float,
        )

        if (
            abs(
                float(
                    np.dot(
                        fallback,
                        up,
                    )
                )
            )
            > 0.9
        ):
            fallback = np.array(
                [0.0, 1.0, 0.0],
                dtype=float,
            )

        x_axis = _unit(
            fallback
            - np.dot(
                fallback,
                up,
            )
            * up
        )

    z_axis = _unit(
        np.cross(
            x_axis,
            up,
        )
    )

    # -----------------------------------------------------------------------
    # Save information about the individual UP sources.
    # -----------------------------------------------------------------------

    source_metadata = {}

    for name, result in source_results.items():
        item = dict(result)

        if item.get("vector") is not None:
            oriented = _orient_like(
                np.asarray(
                    item["vector"],
                    dtype=float,
                ),
                up,
            )

            item["vector"] = (
                oriented.tolist()
            )

            item[
                "agreement_angle_to_final_deg"
            ] = _line_angle_deg(
                oriented,
                up,
            )

            item[
                "agrees_with_final"
            ] = (
                item[
                    "agreement_angle_to_final_deg"
                ]
                <= MAX_SOURCE_AGREEMENT_DEG
            )

        else:
            item[
                "agreement_angle_to_final_deg"
            ] = None

            item[
                "agrees_with_final"
            ] = False

        source_metadata[name] = item

    # -----------------------------------------------------------------------
    # Coordinate system.
    # -----------------------------------------------------------------------

    coord_system = {
        "up_axis": up.tolist(),
        "horizontal_axes": [
            x_axis.tolist(),
            z_axis.tolist(),
        ],
        "up_source": fused["up_source"],
        "up_confidence": float(
            fused["confidence"]
        ),
        "up_source_agreement": (
            fused["agreed_sources"]
        ),
        "up_source_disagreement": (
            fused["disagreed_sources"]
        ),
        "up_sources": source_metadata,
    }

    return {
        "coordinate_system": coord_system,
        "planes": planes,
    }
