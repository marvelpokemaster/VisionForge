import argparse
import os
import sys
import json
import subprocess
from pathlib import Path
from visionforge.spatial.scene_graph import build_scene_graph, save_scene_graph
from visionforge.spatial.queries import SpatialQueryEngine
from visionforge.spatial.viewer import create_digital_twin, launch_viewer
from visionforge.twin.digital_twin import DigitalTwin
from visionforge.persistence import get_backend, persist_run


class StageError(RuntimeError):
    """A pipeline stage failed. The CLI turns it into exit code 1 (main());
    in-process callers (the live session) catch it and record the failure."""


def _stage_env() -> dict:
    """Environment for a `python -m visionforge.<stage>` child: the directory
    this package lives in is put on PYTHONPATH, so the stage is importable
    however the parent was started (pytest's pythonpath, uvicorn, a venv
    without an installed package)."""
    import visionforge
    env = os.environ.copy()
    src_dir = str(Path(visionforge.__file__).resolve().parents[1])
    env["PYTHONPATH"] = src_dir + (os.pathsep + env["PYTHONPATH"] if env.get("PYTHONPATH") else "")
    return env


def _run_stage(cmd, description):
    print(f"Running: {' '.join(cmd)}")
    result = subprocess.run(cmd, env=_stage_env())
    if result.returncode != 0:
        raise StageError(f"{description} failed with exit code {result.returncode}.")


def _write_run_status(out_dir: Path, status: dict):
    with open(out_dir / "run_status.json", "w") as f:
        json.dump(status, f, indent=2)


def _build_and_save_twin(out_dir: Path, status: dict) -> DigitalTwin:
    """Marks the twin stage "running" before the build so a twin.json built
    from THIS status (or a concurrent reader of run_status.json) reflects
    the truth, not a silently-missing stage; marks it "success" after."""
    status["stages"]["twin"] = "running"
    _write_run_status(out_dir, status)

    twin = DigitalTwin.build_from_run_dir(out_dir)
    twin.save(out_dir / "twin.json")

    status["stages"]["twin"] = "success"
    _write_run_status(out_dir, status)
    return twin


def cmd_reconstruct(args):
    print("==================================================")
    print(" VisionForge: Offline Digital Twin Construction")
    print("==================================================")

    video_path = Path(args.video)
    if not video_path.exists():
        print(f"Error: {video_path} not found.")
        sys.exit(1)

    out_dir = Path(args.output)
    out_dir.mkdir(parents=True, exist_ok=True)

    status = {
        "input_type": args.input_type or "unknown",
        "video": str(video_path),
        "stages": {}
    }
    _write_run_status(out_dir, status)

    # Run P0 (Video Ingestion)
    print("[1/6] Extracting frames from {}...".format(video_path))
    p0_dir = out_dir / "p0"
    _run_stage(
        [sys.executable, "-m", "visionforge.video.extract_frames",
         "--input", str(video_path), "--output", str(p0_dir)],
        "P0 (Video Extraction)"
    )
    status["stages"]["p0_frame_extraction"] = "success"
    _write_run_status(out_dir, status)

    # Run P1 (Reconstruction)
    print("[2/6] Running Classical Reconstruction (P1)...")
    p1_dir = out_dir / "p1"
    _run_stage(
        [sys.executable, "-m", "visionforge.reconstruction.pipeline",
         "--frames-dir", str(p0_dir / "frames"), "--output", str(p1_dir)],
        "P1 (Reconstruction)"
    )

    p1_cloud = p1_dir / "reconstruction" / "sparse_cloud.ply"
    if not p1_cloud.exists():
        status["stages"]["p1_reconstruction"] = "failed"
        _write_run_status(out_dir, status)
        print(f"Error: P1 did not produce a sparse cloud at {p1_cloud}.")
        print("This usually means the input video lacks sufficient camera translation "
              "(parallax) for classical SfM to triangulate points. Re-record with real "
              "camera movement through the scene, not a static shot or pure pan.")
        sys.exit(1)
    status["stages"]["p1_reconstruction"] = "success"
    _write_run_status(out_dir, status)

    room_model = _run_geometry_scene_graph_twin(out_dir, status, p1_dir, first_step=3, total_steps=6, seed=args.seed)

    if args.persist:
        print("Persisting session...")
        backend = get_backend()
        summary = persist_run(backend, out_dir.name, out_dir)
        print(f"Persisted: {', '.join(summary['saved'])}")

    print("\nOffline construction complete.")

    if not args.no_viewer:
        print("Launching Digital Twin Viewer...")
        geometries = create_digital_twin(str(p1_cloud), room_model)
        launch_viewer(geometries)


def _run_geometry_scene_graph_twin(out_dir: Path, status: dict, p1_dir: Path, first_step: int, total_steps: int,
                                   seed: int = None) -> dict:
    """The stages downstream of a P1-format reconstruction
    (p1/reconstruction/sparse_cloud.ply + cameras.json): P2 room geometry,
    scene graph, query demo, twin.json. Shared by `reconstruct` (offline
    COLMAP P1) and `live` (live tracker export) so both produce identical
    run directories. Returns the loaded room model."""
    p1_cloud = p1_dir / "reconstruction" / "sparse_cloud.ply"
    step = first_step

    # Run P2 (Room Geometry)
    print(f"[{step}/{total_steps}] Computing Room Geometry (P2)...")
    p2_dir = out_dir / "p2"
    p2_cmd = [sys.executable, "-m", "visionforge.geometry.pipeline",
              "--input", str(p1_cloud), "--output", str(p2_dir)]
    if seed is not None:
        p2_cmd += ["--seed", str(seed)]
    _run_stage(p2_cmd, "P2 (Room Geometry)")
    status["stages"]["p2_room_geometry"] = "success"
    _write_run_status(out_dir, status)
    step += 1

    # Final Phase (Scene Graph)
    print(f"[{step}/{total_steps}] Generating Spatial Scene Graph...")
    room_model_file = p2_dir / "room_model.json"
    if not room_model_file.exists():
        status["stages"]["scene_graph"] = "failed"
        _write_run_status(out_dir, status)
        raise StageError("P2 room model missing.")

    with open(room_model_file, "r") as f:
        room_model = json.load(f)

    cameras_file = p1_dir / "reconstruction" / "cameras.json"
    cameras = None
    if cameras_file.exists():
        with open(cameras_file, "r") as f:
            cameras = json.load(f)

    sg = build_scene_graph(room_model, cameras=cameras)
    save_scene_graph(sg, out_dir / "scene_graph.json")
    print(f"Scene graph saved to {out_dir / 'scene_graph.json'}")
    status["stages"]["scene_graph"] = "success"
    _write_run_status(out_dir, status)
    step += 1

    # Queries
    print(f"[{step}/{total_steps}] Spatial Queries Demo...")
    sqe = SpatialQueryEngine(sg)
    print(f" - Room Dimensions: {sqe.get_room_dimensions()}")
    floor_area = sqe.get_floor_area()
    print(f" - Floor Area: {floor_area['value']:.2f} {floor_area['units']}" if floor_area else " - Floor Area: not measurable")
    largest_wall = sqe.get_largest_wall()
    if largest_wall:
        print(f" - Largest Wall: {largest_wall}")
    nearest_wall = sqe.get_nearest_wall_to_camera()
    if nearest_wall:
        print(f" - Camera distance to nearest wall: {nearest_wall['value']:.3f} {nearest_wall['units']} ({nearest_wall['wall_id']})")
    step += 1

    # Digital Twin
    print(f"[{step}/{total_steps}] Building Digital Twin (twin.json)...")
    _build_and_save_twin(out_dir, status)
    print(f"Digital twin saved to {out_dir / 'twin.json'}")
    return room_model


def cmd_live(args):
    from visionforge.live.intrinsics import CameraIntrinsics
    from visionforge.live.runner import run_live_tracker, run_source

    if getattr(args, "frames_dir", None):
        _live_from_recording(args)
        return

    if args.video is None and args.output is None and args.intrinsics_from is None:
        run_live_tracker()  # webcam demo, as before
        return

    print("==================================================")
    print(" VisionForge: Live Classical Tracking")
    print("==================================================")
    source = 0
    if args.video is not None:
        video_path = Path(args.video)
        if not video_path.exists():
            print(f"Error: {video_path} not found.")
            sys.exit(1)
        source = str(video_path)

    intrinsics = None
    if args.intrinsics_from:
        intrinsics = CameraIntrinsics.from_cameras_json(args.intrinsics_from)
        print(f"Using COLMAP intrinsics from {args.intrinsics_from}")
    else:
        print("No --intrinsics-from given: focal will be GUESSED as max(w, h) at the image centre.")

    total_steps = 5 if args.output else 1
    print(f"[1/{total_steps}] Tracking {'webcam' if source == 0 else source}...")
    try:
        tracker = run_source(source, intrinsics=intrinsics, max_frames=args.max_frames,
                             gui=not args.no_gui, log_every=1 if args.no_gui else 10)
    except RuntimeError as exc:
        print(f"Error: {exc}")
        sys.exit(1)

    if not args.output:
        print(json.dumps(tracker.report(), indent=2))
        return

    out_dir = Path(args.output)
    out_dir.mkdir(parents=True, exist_ok=True)
    status = {
        "input_type": args.input_type or "unknown",
        "video": "webcam" if source == 0 else str(source),
        "mode": "live",
        "stages": {},
    }
    report = tracker.export(out_dir, video=status["video"])
    print(f"Tracking report: frames={report['frames']} keyframes={report['n_keyframes']} "
          f"states={report['state_counts']} lost_episodes={len(report['lost_episodes'])} "
          f"map={report['map_size']} mean_rms={report['mean_reprojection_rms']} "
          f"intrinsics={report['intrinsics_source']}")
    print(f"Wrote {out_dir / 'tracking_report.json'} and p1/reconstruction/{{sparse_cloud.ply, cameras.json}}")
    if report["n_keyframes"] == 0:
        status["stages"]["live_tracking"] = "failed"
        _write_run_status(out_dir, status)
        print("Error: the tracker never initialised (no keyframes), so there is no map to build geometry from. "
              "The input needs real camera translation (parallax); a static shot or pure pan never initialises.")
        sys.exit(1)
    status["stages"]["live_tracking"] = "success"
    _write_run_status(out_dir, status)

    _run_geometry_scene_graph_twin(out_dir, status, out_dir / "p1", first_step=2, total_steps=total_steps,
                                   seed=args.seed)
    print("\nLive construction complete.")


def _live_from_recording(args):
    """`visionforge live --frames-dir <recorded session or its frames/> --output <dir>`:
    the recorded bytes through LiveSession offline (live/offline.py), with the
    recorded configure message (frame size, intrinsics) and the live tracker
    settings, then the usual export -> P2 -> scene graph -> twin."""
    from visionforge.live.offline import replay_recording

    if not args.output:
        print("Error: --frames-dir needs --output <run directory>.")
        sys.exit(1)
    frames_dir = Path(args.frames_dir)
    if not frames_dir.exists():
        print(f"Error: {frames_dir} not found.")
        sys.exit(1)
    out_dir = Path(args.output)
    print("==================================================")
    print(" VisionForge: Live Tracking — offline replay of a recording")
    print("==================================================")
    print(f"[1/5] Replaying {frames_dir} ({'processed frames only' if args.processed_only else 'every received frame'})...")

    def log(st):
        if args.max_frames is None and st["frame_index"] % 10 and not st["is_keyframe"]:
            return
        rms = f"{st['reprojection_rms']:.2f}" if st["reprojection_rms"] is not None else "-"
        print(f"[{st['frame_index']:5d}] {st['state']:12s} tracked={st['n_tracked']:4d} inliers={st['n_inliers']:4d} "
              f"rms={rms:>5s} map={st['map_size']:5d}{'  KF' if st['is_keyframe'] else ''}")

    try:
        session, rec = replay_recording(frames_dir, out_dir, processed_only=args.processed_only,
                                        max_frames=args.max_frames, log=log,
                                        input_type=args.input_type or "unknown", seed=args.seed)
    except (FileNotFoundError, ValueError) as exc:
        print(f"Error: {exc}")
        sys.exit(1)
    report = json.loads((out_dir / "tracking_report.json").read_text())
    tm = report["timing"] or {}
    print(f"Tracking report: frames={report['frames']} keyframes={report['n_keyframes']} "
          f"states={report['state_counts']} lost_episodes={len(report['lost_episodes'])} "
          f"map={report['map_size']} mean_rms={report['mean_reprojection_rms']} "
          f"intrinsics={report['intrinsics_source']} process_ms_p50={tm.get('process_frame_ms_p50')}")
    print(f"Stages: {session.stage_status}")
    print(f"Wrote {out_dir}")
    if session.stage_status.get("live_tracking") != "success":
        sys.exit(1)


def cmd_calibrate(args):
    """`visionforge calibrate --video <phone clip> --output <json>`: P0 + P1
    (COLMAP) on a short clip from the SAME phone in the SAME orientation,
    then the per-camera intrinsics and their median in a cameras.json-style
    list the live protocol accepts as `intrinsics_from_cameras` (the Live
    screen's Intrinsics field). See live/calibrate.py."""
    from visionforge.live.calibrate import run_calibration

    video_path = Path(args.video)
    if not video_path.exists():
        print(f"Error: {video_path} not found.")
        sys.exit(1)
    out_path = Path(args.output)
    work_dir = Path(args.work_dir) if args.work_dir else out_path.with_suffix("").with_name(out_path.stem + "_work")
    print("==================================================")
    print(" VisionForge: Phone Intrinsics Calibration (P0 + P1)")
    print("==================================================")
    try:
        result = run_calibration(video_path, out_path, work_dir, fps=args.fps, max_frames=args.max_frames,
                                 run_stage=_run_stage)
    except StageError as exc:
        print(f"Error: {exc}")
        sys.exit(1)
    except ValueError as exc:
        print(f"Error: {exc}")
        sys.exit(1)
    med = result[0]
    print(f"Calibrated {len(result) - 1} cameras at {med['width']}x{med['height']}: median "
          f"{med['camera_model']} {[round(v, 3) for v in med['camera_params']]}")
    print(f"Wrote {out_path} — paste it into the Live screen's Intrinsics field, or "
          f"`visionforge live --intrinsics-from {out_path}`")


def cmd_twin_build(args):
    run_dir = Path(args.run_dir)
    if not run_dir.exists():
        print(f"Error: run directory {run_dir} not found.")
        sys.exit(1)

    twin = DigitalTwin.build_from_run_dir(run_dir)
    out_path = run_dir / "twin.json"
    twin.save(out_path)
    print(f"Digital twin saved to {out_path}")
    print(json.dumps(twin.provenance, indent=2))


def cmd_persist(args):
    run_dir = Path(args.run_dir)
    if not run_dir.exists():
        print(f"Error: run directory {run_dir} not found.")
        sys.exit(1)

    session_id = args.session_id or run_dir.name
    backend = get_backend()
    summary = persist_run(backend, session_id, run_dir)
    print(f"Persisted session '{session_id}': {', '.join(summary['saved'])}")


def main():
    parser = argparse.ArgumentParser(description="VisionForge CLI")
    subparsers = parser.add_subparsers(dest="command")

    # Offline command
    rec_parser = subparsers.add_parser("reconstruct", help="Run the full offline pipeline on a video")
    rec_parser.add_argument("--video", required=True, help="Input video file")
    rec_parser.add_argument("--output", default="outputs/final_demo", help="Output directory for pipeline artifacts")
    rec_parser.add_argument("--no-viewer", action="store_true", help="Skip launching the Open3D viewer at the end")
    rec_parser.add_argument("--input-type", choices=["synthetic", "real"], default=None,
                             help="Whether --video is a synthetic rendered clip or real (physical-camera) footage; "
                                  "recorded in run_status.json / twin.json provenance. Defaults to 'unknown' if omitted.")
    rec_parser.add_argument("--persist", action="store_true",
                             help="Also persist the session (room model, scene graph, twin, measurements, "
                                  "processing status) through the configured PersistenceBackend "
                                  "(Supabase if SUPABASE_URL/SUPABASE_KEY are set, else outputs/ JSON).")
    rec_parser.add_argument("--seed", type=int, default=None,
                             help="Seed for the P2 geometry stage's RNGs (default: unseeded, current behaviour)")

    # Live command
    live_parser = subparsers.add_parser("live", help="Live classical tracking: webcam demo (no args) or a video file")
    live_parser.add_argument("--video", default=None, help="Video file to track (default: webcam 0)")
    live_parser.add_argument("--output", default=None,
                             help="Run directory to export into (p1/reconstruction/*, tracking_report.json), then run "
                                  "P2 geometry, scene graph and twin.json exactly like `reconstruct`")
    live_parser.add_argument("--intrinsics-from", default=None,
                             help="A P1 cameras.json (e.g. outputs/final_demo/p1/reconstruction/cameras.json) whose "
                                  "COLMAP camera model/params give the intrinsics; otherwise focal = max(w, h) is guessed")
    live_parser.add_argument("--no-gui", action="store_true", help="Headless: no OpenCV window")
    live_parser.add_argument("--max-frames", type=int, default=None, help="Stop after N frames")
    live_parser.add_argument("--input-type", choices=["synthetic", "real"], default=None,
                             help="Recorded in run_status.json / twin.json provenance (default 'unknown')")
    live_parser.add_argument("--seed", type=int, default=None,
                             help="Seed for the P2 geometry stage's RNGs (default: unseeded, current behaviour)")
    live_parser.add_argument("--frames-dir", default=None,
                             help="Replay a RECORDED live session offline (outputs/<id> or outputs/<id>/frames, written "
                                  "by a session started with {\"record\": true}) with its recorded intrinsics; "
                                  "needs --output. Uses the live tracker settings (keyframe_min_gap 3, map cap).")
    live_parser.add_argument("--processed-only", action="store_true",
                             help="--frames-dir only: feed just the frames the live tracker saw (skip the ones "
                                  "backpressure dropped) to reproduce the live run")

    # Calibrate command
    cal_parser = subparsers.add_parser("calibrate",
                                       help="Estimate a phone's intrinsics with COLMAP (P0 + P1) from a short clip")
    cal_parser.add_argument("--video", required=True,
                            help="A 20-30 s clip from the SAME phone in the SAME orientation as the live run, "
                                 "slow sideways walk in a textured room")
    cal_parser.add_argument("--output", required=True,
                            help="Output JSON: a cameras.json-style list, median first, then one entry per "
                                 "registered frame (each with width/height)")
    cal_parser.add_argument("--work-dir", default=None,
                            help="Where P0/P1 write (default: <output stem>_work next to the output)")
    cal_parser.add_argument("--fps", type=float, default=2.0, help="Frame sampling rate for P0 (default 2)")
    cal_parser.add_argument("--max-frames", type=int, default=None, help="Cap on extracted frames")

    # Twin command
    twin_parser = subparsers.add_parser("twin", help="Digital twin data layer commands")
    twin_subparsers = twin_parser.add_subparsers(dest="twin_command")
    twin_build_parser = twin_subparsers.add_parser("build", help="Build/rebuild twin.json from an existing run directory")
    twin_build_parser.add_argument("--run-dir", required=True, help="Run directory produced by `visionforge reconstruct`")

    # Persist command
    persist_parser = subparsers.add_parser("persist", help="Persist an existing run directory through the configured PersistenceBackend")
    persist_parser.add_argument("--run-dir", required=True, help="Run directory produced by `visionforge reconstruct`")
    persist_parser.add_argument("--session-id", default=None, help="Session id to persist under (defaults to the run directory's name)")

    args = parser.parse_args()

    try:
        if args.command == "reconstruct":
            cmd_reconstruct(args)
        elif args.command == "live":
            cmd_live(args)
        elif args.command == "calibrate":
            cmd_calibrate(args)
        elif args.command == "twin":
            if args.twin_command == "build":
                cmd_twin_build(args)
            else:
                twin_parser.print_help()
        elif args.command == "persist":
            cmd_persist(args)
        else:
            parser.print_help()
    except StageError as exc:
        print(f"Error: {exc}")
        sys.exit(1)

if __name__ == "__main__":
    main()
