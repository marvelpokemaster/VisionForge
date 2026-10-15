"""IncrementalRoomModel (geometry/incremental.py): gating, small-cloud
result, and a growing cloud fed in cumulative slices."""
import numpy as np
import open3d as o3d

from visionforge.geometry.api import GeometryOptions, build_room_model, empty_room_model_result
from visionforge.geometry.incremental import IncrementalRoomModel
from test_geometry_api import canon, deterministic_segment_plane, load_case


def test_empty_result_has_null_measurements_and_reason():
    r = empty_room_model_result(17, "too few")
    assert r.n_planes == 0 and r.reason == "too few" and r.room_model["reason"] == "too few"
    assert all(v is None for v in r.room_model["room"].values())
    assert r.statistics["geometry"]["num_planes"] == 0 and r.n_input_points == 17


def test_incremental_small_cloud_gives_empty_result_not_a_guess():
    inc = IncrementalRoomModel(min_points=200, min_new_points=10, min_interval_s=0.0)
    res = inc.update(np.random.default_rng(0).normal(size=(50, 3)), None, now=0.0)
    assert res is not None and res.n_planes == 0 and "50 points < min_points=200" in res.reason
    assert res.room_model["room"]["length"] is None
    assert inc.latest is res and inc.n_fits == 1


def test_incremental_growth_gating():
    inc = IncrementalRoomModel(min_points=10, min_new_points=100, min_interval_s=0.0)
    pts = np.random.default_rng(1).normal(size=(500, 3))
    first = inc.update(pts[:150], now=0.0)
    assert first is not None
    assert inc.update(pts[:249], now=1.0) is None          # grew by 99 < 100
    assert inc.latest is first and inc.n_skipped == 1
    assert inc.update(pts[:250], now=2.0) is not None      # grew by exactly 100
    assert inc.n_fits == 2


def test_incremental_time_gating_with_injected_clock():
    inc = IncrementalRoomModel(min_points=10, min_new_points=1, min_interval_s=5.0)
    pts = np.random.default_rng(2).normal(size=(400, 3))
    assert inc.update(pts[:100], now=100.0) is not None
    assert inc.update(pts[:300], now=104.9) is None        # grew enough, too soon
    assert inc.update(pts[:300], now=105.0) is not None    # exactly min_interval_s later
    assert inc.update(pts[:300], now=200.0) is None        # waited, but did not grow
    assert inc.n_fits == 2 and inc.n_skipped == 2


def test_incremental_growing_cloud_matches_one_shot_and_never_fabricates(monkeypatch):
    pcd, cams, *_ = load_case("final_demo")
    pts = np.asarray(pcd.points)
    rng = np.random.default_rng(3)
    order = rng.permutation(len(pts))             # the cloud grows in random point order
    slices = [pts[order[: int(len(pts) * f)]] for f in (0.1, 0.3, 0.5, 0.8, 1.0)]

    monkeypatch.setattr(o3d.geometry.PointCloud, "segment_plane", deterministic_segment_plane(0))
    one_shot = build_room_model(slices[-1], cams, GeometryOptions(), seed=0)

    inc = IncrementalRoomModel(min_points=300, min_new_points=1, min_interval_s=0.0, seed=0)
    results = []
    for i, s in enumerate(slices):
        r = inc.update(s, cams, now=float(i))
        assert r is not None
        results.append(r)
    # slice 0 (170 points) is below min_points -> explicit empty result
    assert results[0].n_planes == 0 and results[0].reason.startswith("170 points < min_points")
    # earlier slices never have more planes than the final one, and nothing is fabricated:
    # every plane's support is bounded by the points it was fitted on
    n_final = results[-1].n_planes
    for r, s in zip(results, slices):
        assert r.n_planes <= n_final
        assert all(p["support"] <= r.statistics["point_cloud"]["cleaned_points"] <= len(s) for p in r.room_model["planes"])
    assert n_final == one_shot.n_planes >= 2
    # the final incremental result equals the one-shot result on the same cloud
    assert canon(results[-1].room_model) == canon(one_shot.room_model)
    assert results[-1].statistics["incremental"]["input_points"] == len(pts) and inc.n_fits == 5


def test_incremental_prefilter_reduces_fit_points():
    pcd, cams, *_ = load_case("final_demo")
    pts = np.asarray(pcd.points)
    inc = IncrementalRoomModel(min_points=10, prefilter_voxel_size=1.0)
    r = inc.update(pts, cams, now=0.0)
    assert r.statistics["incremental"]["fit_points"] < len(pts)
    assert r.statistics["incremental"]["prefilter_voxel_size"] == 1.0
