"""In-memory P2 (geometry/api.py, geometry/incremental.py) and its
equivalence with the file-based pipeline.main().

Fixtures in tests/fixtures/p2/<name>/ were produced by the PRE-REFACTOR
pipeline.main() on the two real clouds (COLMAP's final_demo and the live
tracker's live_synth_30): the input ply + cameras.json, the RANSAC draws
(model + inliers of every Open3D segment_plane call, in order), the
resulting room_model.json / statistics.json, and the list of files written.

Open3D 0.20's segment_plane is NOT reproducible under o3d.utility.random.seed
(test_seeded_segment_plane_is_not_reproducible proves it), so:
  * EXACT equivalence (every number of room_model.json, every file) is proven
    by replaying the recorded RANSAC draws into both the new main() and
    build_room_model: given identical RANSAC output, everything else must be
    identical to the pre-refactor output.
  * With real RANSAC the two paths are compared to tolerance on plane count,
    normals and supports (types are known to flip on live_synth_30).
"""
import json
import subprocess
import sys
from pathlib import Path

import numpy as np
import open3d as o3d
import pytest

from visionforge.geometry import pipeline
from visionforge.geometry.api import GeometryOptions, build_room_model, resolve_thresholds
from visionforge.geometry.point_cloud import clean_point_cloud

FIXTURES = Path(__file__).parent / "fixtures" / "p2"
CASES = ["final_demo", "live_synth_30"]


def load_case(name):
    d = FIXTURES / name
    pcd = o3d.io.read_point_cloud(str(d / "sparse_cloud.ply"))
    cams = json.loads((d / "cameras.json").read_text())
    ref = json.loads((d / "room_model_reference.json").read_text())
    stats_ref = json.loads((d / "statistics_reference.json").read_text())
    draws = json.loads((d / "ransac_draws.json").read_text())
    files = json.loads((d / "output_files_reference.json").read_text())
    return pcd, cams, ref, stats_ref, draws, files


def replay_segment_plane(monkeypatch, draws):
    """Make PointCloud.segment_plane return the recorded draws in order,
    asserting it is called on clouds of the recorded sizes with the recorded
    parameters (so the call SEQUENCE is proven identical too)."""
    calls = {"i": 0}

    def fake(self, distance_threshold, ransac_n, num_iterations, probability=0.99999999):
        i = calls["i"]
        assert i < len(draws), "more segment_plane calls than recorded"
        d = draws[i]
        assert len(self.points) == d["n_points"], (i, len(self.points), d["n_points"])
        assert distance_threshold == pytest.approx(d["distance_threshold"])
        assert (ransac_n, num_iterations) == (d["ransac_n"], d["num_iterations"])
        calls["i"] += 1
        return np.array(d["model"]), list(d["inliers"])

    monkeypatch.setattr(o3d.geometry.PointCloud, "segment_plane", fake)
    return calls


def deterministic_segment_plane(seed=0):
    """A test-only, fully deterministic RANSAC plane fit with the same
    contract as Open3D's (model [a,b,c,d] with unit normal, inlier indices),
    so incremental-vs-one-shot equality can be asserted exactly."""
    def fake(self, distance_threshold, ransac_n, num_iterations, probability=0.99999999):
        P = np.asarray(self.points)
        n = len(P)
        best = (-1, None)
        # the sample sequence is a pure function of (seed, cloud): identical clouds -> identical draws
        digest = int(abs(float(P.sum())) * 1e6) % (2**31)
        local = np.random.default_rng([seed, n, digest])
        for _ in range(min(num_iterations, 200)):
            idx = local.choice(n, 3, replace=False)
            a, b, c = P[idx]
            nrm = np.cross(b - a, c - a)
            if np.linalg.norm(nrm) < 1e-12:
                continue
            nrm /= np.linalg.norm(nrm)
            d = -nrm @ a
            dist = np.abs(P @ nrm + d)
            count = int((dist < distance_threshold).sum())
            if count > best[0]:
                best = (count, (nrm, d))
        nrm, d = best[1]
        inl = np.flatnonzero(np.abs(P @ nrm + d) < distance_threshold)
        return np.array([*nrm, d]), inl.tolist()

    return fake


def canon(obj):
    """JSON round-trip so numpy scalars / tuples compare like file contents."""
    return json.loads(json.dumps(obj, sort_keys=True))


# ----------------------------------------------------------- options / API
def test_geometry_options_defaults_match_the_cli_parser():
    args = pipeline.build_parser().parse_args(["--input", "x", "--output", "y"])
    assert pipeline.options_from_args(args) == GeometryOptions()
    assert args.seed is None and args.cameras is None


def test_resolve_thresholds_matches_main_fractions():
    pts = np.array([[0, 0, 0], [3, 4, 0.0]])
    diag, voxel, thr = resolve_thresholds(pts, GeometryOptions())
    assert diag == 5.0 and voxel == pytest.approx(0.025) and thr == pytest.approx(0.05)
    assert resolve_thresholds(pts, GeometryOptions(voxel_size=0.1, plane_distance_threshold=0.2))[1:] == (0.1, 0.2)
    with pytest.raises(ValueError, match="zero spatial extent"):
        resolve_thresholds(np.zeros((3, 3)), GeometryOptions())


def test_build_room_model_rejects_empty_cloud():
    with pytest.raises(ValueError, match="empty"):
        build_room_model(np.zeros((0, 3)), None)


def test_clean_point_cloud_is_deterministic():
    pcd, *_ = load_case("live_synth_30")
    a = np.asarray(clean_point_cloud(pcd, voxel_size=0.3)[0].points)
    b = np.asarray(clean_point_cloud(pcd, voxel_size=0.3)[0].points)
    assert a.shape == b.shape and np.array_equal(a, b)


def test_seeded_segment_plane_is_not_reproducible():
    """Documents the Open3D 0.20 behaviour the equivalence strategy rests on.
    If this ever FAILS (all six seeded calls identical), Open3D became
    reproducible and the exact test can drop the replay."""
    pcd, *_ = load_case("live_synth_30")
    clean, _ = clean_point_cloud(pcd, voxel_size=0.28)
    models = []
    for _ in range(6):
        o3d.utility.random.seed(0)
        m, inl = clean.segment_plane(distance_threshold=0.56, ransac_n=3, num_iterations=1000)
        models.append((tuple(np.round(m, 9)), len(inl)))
    assert len(set(models)) > 1, models


# ------------------------------------------------------- exact equivalence
@pytest.mark.parametrize("name", CASES)
def test_build_room_model_equals_prerefactor_output_given_same_ransac_draws(monkeypatch, name):
    pcd, cams, ref, stats_ref, draws, _ = load_case(name)
    calls = replay_segment_plane(monkeypatch, draws)
    res = build_room_model(np.asarray(pcd.points), cams, GeometryOptions(), seed=0)
    assert calls["i"] == len(draws)
    assert canon(res.room_model) == ref
    stats = canon(res.statistics)
    stats.pop("processing_time_seconds")
    assert stats == stats_ref
    # per-plane inlier indices: counts equal the support, every index used once, and the
    # points lie near the plane. Open3D refines the equation on the inliers after RANSAC
    # (so a RANSAC inlier can sit a little beyond the threshold of the refined plane) and
    # merge_coplanar_planes accepts segments whose offset differs by up to 2x threshold.
    thr = res.statistics["resolved_thresholds"]["plane_distance_threshold"]
    for p in res.room_model["planes"]:
        idx = res.plane_inliers[p["id"]]
        assert len(idx) == p["support"]
        a, b, c, d = p["equation"]
        dist = np.abs(res.cleaned_points[idx] @ np.array([a, b, c]) + d) / np.linalg.norm([a, b, c])
        assert dist.max() <= 2.0 * thr, (p["id"], dist.max(), thr)
        assert np.median(dist) <= thr
    assert len(set(np.concatenate(list(res.plane_inliers.values())))) == sum(p["support"] for p in res.room_model["planes"])


@pytest.mark.parametrize("name", CASES)
def test_main_writes_prerefactor_files_given_same_ransac_draws(monkeypatch, tmp_path, name):
    pcd, cams, ref, stats_ref, draws, files_ref = load_case(name)
    d = FIXTURES / name
    calls = replay_segment_plane(monkeypatch, draws)
    monkeypatch.setattr(sys, "argv", ["pipeline", "--input", str(d / "sparse_cloud.ply"),
                                      "--output", str(tmp_path), "--cameras", str(d / "cameras.json"), "--seed", "0"])
    pipeline.main()
    assert calls["i"] == len(draws)
    assert json.loads((tmp_path / "room_model.json").read_text()) == ref
    stats = json.loads((tmp_path / "statistics.json").read_text())
    assert stats.pop("processing_time_seconds") > 0
    assert stats == stats_ref
    files = sorted(str(p.relative_to(tmp_path)).replace("\\", "/") for p in tmp_path.rglob("*") if p.is_file())
    assert files == files_ref
    # the per-plane PLYs hold exactly the support points
    for p in ref["planes"]:
        assert len(o3d.io.read_point_cloud(str(tmp_path / p["ply_path"])).points) == p["support"]
    raw = o3d.io.read_point_cloud(str(tmp_path / "pointcloud" / "raw.ply"))
    assert len(raw.points) == len(pcd.points) and raw.has_colors() == pcd.has_colors()
    cleaned = o3d.io.read_point_cloud(str(tmp_path / "pointcloud" / "cleaned.ply"))
    assert len(cleaned.points) == stats_ref["point_cloud"]["cleaned_points"] and cleaned.has_normals()


# --------------------------------------------------- real-RANSAC tolerance
def match_planes(planes_a, planes_b):
    """Greedy match by plane geometry (normal direction, then offset), since
    RANSAC can return the same physical planes in a different order."""
    pairs = []
    used = set()
    for p in planes_a:
        best, best_score = None, -1.0
        for j, q in enumerate(planes_b):
            if j in used:
                continue
            score = abs(float(np.dot(p["normal"], q["normal"]))) - 0.01 * abs(p["equation"][3] - q["equation"][3])
            if score > best_score:
                best, best_score = j, score
        if best is not None:
            used.add(best)
            pairs.append((p, planes_b[best]))
    return pairs


# What real (unseedable) RANSAC keeps stable on each cloud, measured over repeated runs of the
# pre-refactor code: final_demo always gives the same 3 planes with the same labels; on
# live_synth_30 the far wall is always found but the two small side-wall segments vary in
# count (3-4 planes), order and label (docs/live_tracking.md §6).
TOLERANCE_EXPECTATIONS = {
    "final_demo": dict(count_slack=0, support_tol=0.10, types_stable=True),
    "live_synth_30": dict(count_slack=1, support_tol=0.15, types_stable=False),
}


@pytest.mark.parametrize("name", CASES)
def test_main_and_build_room_model_agree_to_tolerance_with_real_ransac(tmp_path, name):
    exp = TOLERANCE_EXPECTATIONS[name]
    pcd, cams, ref, *_ = load_case(name)
    d = FIXTURES / name
    proc = subprocess.run([sys.executable, "-m", "visionforge.geometry.pipeline", "--input", str(d / "sparse_cloud.ply"),
                           "--output", str(tmp_path), "--cameras", str(d / "cameras.json"), "--seed", "0"],
                          capture_output=True, text=True, env={**__import__("os").environ, "PYTHONPATH": "src"})
    assert proc.returncode == 0, proc.stderr
    via_main = json.loads((tmp_path / "room_model.json").read_text())
    res = build_room_model(np.asarray(pcd.points), cams, GeometryOptions(), seed=0)
    mine = res.room_model["planes"]
    for other in (via_main, ref):
        assert abs(len(mine) - len(other["planes"])) <= exp["count_slack"], (len(mine), len(other["planes"]))
        pairs = match_planes(mine, other["planes"])
        assert len(pairs) >= min(len(mine), len(other["planes"]))
        for p, q in pairs:
            assert abs(np.dot(p["normal"], q["normal"])) > 0.995, (p["id"], p["normal"], q["id"], q["normal"])
            assert abs(p["support"] - q["support"]) <= exp["support_tol"] * q["support"], (p["id"], p["support"], q["support"])
        # the dominant plane is the same physical plane with nearly the same support
        dom_p = max(mine, key=lambda p: p["support"])
        dom_q = max(other["planes"], key=lambda p: p["support"])
        assert abs(np.dot(dom_p["normal"], dom_q["normal"])) > 0.999
        assert abs(dom_p["support"] - dom_q["support"]) <= 0.05 * dom_q["support"]
        assert canon(res.room_model["coordinate_system"] or {}).keys() == canon(other["coordinate_system"] or {}).keys()
        assert res.room_model["room"]["height_method"] == other["room"]["height_method"]
    if exp["types_stable"]:
        assert sorted(p["type"] for p in mine) == sorted(p["type"] for p in ref["planes"])
