# Live screen on Android — human test checklist

What the desktop verification could and could not cover (see
`docs/live_tracking.md` §10): the Live screen was driven end to end in a real
Chrome on the PC with a **video file** source (INITIALIZING → TRACKING, planes
drawn on each twin update, Stop → finished → session view) and with Chrome's
**fake camera device** (getUserMedia path works; no parallax → stays
INITIALIZING, finishes as an honest failed session). **Nothing has been run on
an emulator or a phone.** This is what a human with a device needs to do and
report back.

## 0. Build and install

```
cd frontend
# emulator: .env.production already says VITE_API_BASE_URL=http://10.0.2.2:8000
# phone:    set it to the PC's LAN IP, e.g. VITE_API_BASE_URL=http://192.168.1.20:8000 (ipconfig -> IPv4 of the Wi-Fi adapter)
npm run build && npx cap sync android
npx cap open android      # then Run from Android Studio
```

Backend on the PC, bound to all interfaces: `uvicorn visionforge.api.app:app --host 0.0.0.0 --port 8000`
(from the repo root with `PYTHONPATH=src`). Phone and PC on the **same Wi-Fi**;
Windows firewall must allow inbound TCP 8000 (`netsh advfirewall firewall add
rule name="VisionForge API" dir=in action=allow protocol=TCP localport=8000`).
Sanity check first, in the phone's Chrome: `http://<PC-IP>:8000/sessions` must
return JSON. If it does not, nothing in the app will work either.

The WebSocket goes to the same host (`ws://<PC-IP>:8000/live/<id>`, derived in
`frontend/src/live/wsUrl.ts`); `capacitor.config.ts` serves the app from
`http://localhost` (`androidScheme: 'http'`), so a plain `ws://` is **not**
mixed content. Nothing else blocks it: `usesCleartextTraffic="true"` is set
in the manifest.

## 1. Emulator caveat

The emulator's virtual camera (the rendered room with the moving "person", or
a webcam pass-through) gives **no real parallax**: expect the big banner to
stay **INITIALIZING** ("translate the camera sideways"). That is the tracker
refusing to initialise without translation, not a bug. On the emulator use the
**video file** source instead: push a browser-playable clip, e.g.
`adb push data/input/synthetic_box_room_30fps.webm /sdcard/Download/`
(generate it with `python scripts/generate_synthetic_clip.py --output
data/input/synthetic_box_room_30fps.webm --frames 360 --fps 30 --fourcc VP80`
— the default `.mp4` clips are MPEG-4 part 2, which the WebView cannot play).

## 2. Camera permission

The first Start with the camera source should trigger Android's CAMERA
permission prompt (declared in `AndroidManifest.xml`; Capacitor's WebView
forwards the `getUserMedia` permission request). If instead the screen shows
`Could not start camera: ... NotAllowedError` or `getUserMedia is not available`
even after granting, **that is the finding to report**: the WebView path is
refused and the fallback is a native camera-preview plugin
(`@capacitor-community/camera-preview`) feeding the same `FrameSource`
interface. Please paste the exact error text.

## 3. What "good" looks like on a physical phone

Walk **sideways** (translate, do not just pan) along a wall of a normal,
textured room, 1–2 m/s, phone in landscape or portrait (both are fine; the
frame is downscaled to 640 px wide before tracking).

- Banner: INITIALIZING for the first second or two, then **TRACKING** and
  mostly staying there. Short **LOST** flashes when you swing fast or point at
  a blank wall are expected; it should re-initialise (the `segment` number in
  the strip increases) once you move sideways again.
- Strip: `tracked` 100–400, `inliers` close to `tracked` while TRACKING,
  `map` growing by tens to hundreds per second, `keyframes` growing every
  second or so, `dropped` (server) small, `skipped` (client) mostly from
  `rate`/`busy` (encode time on the phone), measured fps 5–10.
- Viewer: within 1–3 s of TRACKING a twin update arrives; first ones may say
  `no geometry yet: N points < min_points=200` — honest, keep moving. Then
  planes appear and are redrawn on every update; points (the live map) appear
  as white dots.
- Stop: the banner stops, a "finished: … frames processed" line shows the
  stage status, and the app jumps to the session view for that id with the
  3D twin and measurements.

Expect P2's known weakness (`docs/live_tracking.md` §4/§6): the largest plane
is labelled **floor** even when it is a wall. Report the labels as they are.

## 4. What to paste back

1. The status strip values at ~5 s, ~15 s and just before Stop (a screenshot is
   enough): state, tracked, inliers, map, keyframes, segment, dropped, skipped
   (with the breakdown in parentheses), fps.
2. The uvicorn lines for the session: the `WebSocket /live/<id> [accepted]`
   line, any `Error`/`Traceback`, the `Classifications: {...}` line and
   `GET /sessions/<id>/twin ... 200`.
3. The plane count and labels of the first twin update that drew geometry, and
   of the finished session (sidebar → Inspect, or
   `curl http://<PC-IP>:8000/sessions/<id>/room_model | jq '.planes[] | {id,type,support}'`).
4. `outputs/<id>/tracking_report.json` from the PC (frames, keyframes,
   state_counts, lost_episodes, map_size, timing) and
   `outputs/<id>/run_status.json` (`live.dropped`, `live.source_size`).
5. Phone model, Android version, whether the camera prompt appeared, and how
   it felt: did the banner match what you were doing (LOST when you swung,
   TRACKING when you walked)?
