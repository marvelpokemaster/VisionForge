# Live screen on Android — human test checklist

What the desktop verification could and could not cover (see
`docs/live_tracking.md` §10): the Live screen was driven end to end in a real
Chrome on the PC with a **video file** source (INITIALIZING → TRACKING, planes
drawn on each twin update, Stop → finished → session view) and with Chrome's
**fake camera device** (getUserMedia path works; no parallax → stays
INITIALIZING, finishes as an honest failed session). Stage 1 (emulator) has
since been done — results below. **Stage 2 (a physical phone) is next.**

## 0. Build, install, reach the PC

```
cd frontend
# .env.production: VITE_API_BASE_URL=http://192.168.1.37:8000  (the PC's Wi-Fi IPv4; `ipconfig`)
npm run build && npx cap sync android
grep -o "192.168.1.37:8000" dist/assets/*.js | sort | uniq -c     # the build default really is in the bundle
npx cap open android      # then Run from Android Studio
```

**The build default is only a default.** Both the Live screen header and the
sessions sidebar have a **Backend** field: type a URL, press Enter/Apply, and
every REST call, the live WebSocket and the PLY loader use it from then on
(`frontend/src/lib/backend.ts::apiBase()` is the one function they all read;
the value is kept in localStorage, so it survives restarts; **Reset** goes back
to the build default). Next to it: `using <url>` (what is in effect) and
`connection: ok (N sessions, M ms)` / `failed: <reason>` from a `GET /sessions`
probe (5 s timeout, **Retry** re-runs it). So:

- emulator → Backend = `http://10.0.2.2:8000`
- phone → Backend = `http://<PC Wi-Fi IPv4>:8000`

with no rebuild in between. Do not press Start until the probe says **ok**.

Backend on the PC, bound to all interfaces (from the repo root):

```
uvicorn visionforge.api.app:app --host 0.0.0.0 --port 8000
```

(`pytest.ini` sets `pythonpath = src` for tests only; for uvicorn either run
from an activated `.venv` with the package installed, or `set PYTHONPATH=src`
first.) Phone and PC on the **same Wi-Fi**. A guest / "AP isolation" Wi-Fi
blocks phone → PC traffic entirely; a mobile hotspot from the phone with the PC
joined to it works too (then the PC IP changes: `ipconfig` again).

**Windows firewall:** inbound TCP 8000 is blocked by default on a Windows PC,
and uvicorn on `0.0.0.0` does not change that. Add the rule once, from an
**administrator** PowerShell / cmd:

```
netsh advfirewall firewall add rule name="VisionForge API" dir=in action=allow protocol=TCP localport=8000
```

(`netsh advfirewall firewall show rule name="VisionForge API"` to check,
`... delete rule name="VisionForge API"` to remove.) If the Wi-Fi network is
classified as *Public* in Windows, the rule above still applies (it is not
profile-restricted); if the probe still fails, temporarily
`netsh advfirewall set allprofiles state off`, retest, and turn it back on.

Sanity check before the app: in the phone's Chrome,
`http://<PC-IP>:8000/sessions` must return JSON. If it does not, nothing in the
app will work either — fix the network first (the Backend field's probe is the
same request).

The WebSocket goes to the same host (`ws://<PC-IP>:8000/live/<id>`, derived in
`frontend/src/live/wsUrl.ts` from the same `apiBase()`); `capacitor.config.ts`
serves the app from `http://localhost` (`androidScheme: 'http'`), so a plain
`ws://` is **not** mixed content, and `usesCleartextTraffic="true"` is set in
the manifest.

## 1. Stage 1 — emulator (done 2026-10-16)

Android Studio emulator, build with `VITE_API_BASE_URL=http://10.0.2.2:8000`,
uvicorn on the PC. Observed:

- Camera permission prompt appeared; getUserMedia succeeded (virtual camera).
- `WebSocket /live/<id>` accepted; the status strip went live: **254
  features tracked**, banner honestly **INITIALIZING** throughout — the
  emulator's virtual camera is static, so no parallax, exactly the caveat
  below. Not a bug.
- **0.2 fps delivered**: the emulator JPEG-encodes the canvas in software, so
  almost every pump tick was a `busy` skip (encode still in flight). The pump
  behaved as designed (never queued, counted the skips); the number is the
  emulator's, not the phone's.
- Stop → `finished` → session list, the session marked `live_tracking:
  failed` / `twin: success`.

Three issues found, all fixed in step 6 prep:

| | Finding | Fix |
|---|---|---|
| (a) | Session view showed `GET …/measurements failed: 404` for the failed live session instead of the twin's `stage_status` | `lib/sessionLoad.ts`: twin first, then measurements; a 404 there keeps the twin and the view shows *"no geometry: live tracking failed (never initialised)"* with the stage list and provenance footer |
| (b) | The WebM test clip did not decode in the emulator's WebView (`no supported source was found`) | `generate_synthetic_clip.py --fourcc avc1` now writes real H.264 (Media Foundation on this PC; a clear error otherwise). See §2 |
| (c) | Android back from the file picker exited the app instead of returning to the Live screen | `@capacitor/app` 8.1.2 (pinned) `backButton` listener in `lib/backButton.ts`: running session → Stop; Live screen / a session → sessions list; sessions list → exit |

### Emulator caveats (still true)

The emulator's virtual camera (the rendered room with the moving "person", or
a webcam pass-through) gives **no real parallax**: expect the big banner to
stay **INITIALIZING** ("translate the camera sideways"). On the emulator use
the **video file** source instead. The WebView's software JPEG encoder caps the
delivered rate at well under 1 fps there; a phone encodes in hardware.

## 2. Test clips for the file source

The default `.mp4` clips the generator writes are MPEG-4 part 2 (`mp4v`),
which OpenCV reads but no browser or WebView plays. Two browser-playable
options, same frames:

```
# H.264 in .mp4 — plays in every Android WebView / Chrome (preferred for the phone)
python scripts/generate_synthetic_clip.py --output data/input/synthetic_box_room_30fps_h264.mp4 --frames 360 --fps 30 --fourcc avc1
# VP8 in .webm — needs a VP8-capable WebView
python scripts/generate_synthetic_clip.py --output data/input/synthetic_box_room_30fps.webm --frames 360 --fps 30 --fourcc VP80
```

`--fourcc avc1`: OpenCV's pip wheel ships an FFmpeg **without** an H.264
encoder (it looks for Cisco's `openh264-<ver>-win64.dll` and prints "Failed to
load OpenH264 library"); on Windows the script therefore tries the Media
Foundation backend first, which encodes H.264 natively — on this PC that works
(`Codec on disk: h264`). If neither can, the script exits with the DLL
download / `ffmpeg -c:v libx264` alternatives instead of writing an empty
file (it re-reads the output and checks the frame count). The WebM clip
**needs a VP8-capable WebView**: the emulator's system WebView refused it
(`no supported source was found`); a real phone's Chrome-based WebView should
play it — if it does not, use the H.264 clip, or the camera.

Push either to the device: `adb push data/input/<clip> /sdcard/Download/`, then
Source = *video file* → pick it from Downloads.

## 3. Stage 2 — physical phone, step by step

Testing is part of development: do all ten, then paste back what §4 asks for.

1. **Phone:** Settings → About → tap *Build number* 7× → Developer options →
   enable **USB debugging**. Connect by USB, accept the "Allow USB debugging"
   prompt. `adb devices` on the PC must list it as `device` (not
   `unauthorized`).
2. **Android Studio:** `cd frontend && npx cap open android`; in the device
   dropdown select **the phone** (not the emulator) → Run ▶. First install
   takes a minute. The app opens on the sessions list.
3. **Same Wi-Fi:** phone on the same network as the PC (not mobile data; not a
   guest network). On the PC `ipconfig` → *Wireless LAN adapter Wi-Fi* → IPv4
   — currently **192.168.1.37**. Backend running on the PC with `--host
   0.0.0.0`; firewall rule from §0 added.
4. **Backend field** (sessions sidebar or Live screen header): type
   `http://192.168.1.37:8000` → Enter. The line below must read
   **`connection: ok (N sessions, … ms)`**. If it says `failed`, stop here
   and fix the network (§0: phone Chrome → `http://192.168.1.37:8000/sessions`
   must show JSON; firewall; same Wi-Fi). Nothing else can work until it is ok.
5. **● Live tracking** → Source = **camera** → **Start**. Allow the camera
   permission prompt. The preview shows the rear camera; the strip starts
   counting frames and `tracked` features; the banner is amber INITIALIZING.
6. **Hold the phone upright** (portrait, camera at chest height, pointed at a
   wall / corner 1.5–3 m away in a normally lit, **textured** room: posters,
   furniture, books — not a blank white wall, not a window).
7. **Walk slowly SIDEWAYS** 2–3 m — translate the phone, keep it pointed the
   same way. Do **not** just rotate on the spot: rotation gives no parallax
   and the tracker will refuse to initialise (that is the design, not a bug).
   About 0.3–0.5 m/s.
8. **Expect INITIALIZING → TRACKING within a few seconds** of starting to
   move (the banner turns green, `inliers` close to `tracked`, `map` and
   `keyframes` growing). Within 1–3 s of TRACKING the viewer gets a twin
   update: first maybe "no geometry yet: N points < min_points=200", then
   planes and white map points drawn and redrawn on each update.
9. **Keep walking 20–30 s**, slowly, along the wall and then along the next
   one if there is room; glance at the strip now and then (`fps`, `skipped`
   breakdown, `dropped`). Short red LOST flashes on a fast swing are expected;
   it should re-initialise (`segment` increments) when you move sideways again.
10. **Stop.** The banner stops, a "finished: … frames processed" line shows
    the stage status, and the app jumps to the session view for that id with
    the 3D twin and Room Measurements (or, if it never initialised, the honest
    "no geometry: live tracking failed (never initialised)" notice). Android
    back from there returns to the sessions list.

Expect P2's known weakness (`docs/live_tracking.md` §4/§6): the largest plane
may be labelled **floor** even when it is a wall. Report the labels as they are.

## 4. What to paste back

1. **The status strip at Stop** (screenshot, or type it): state, frame,
   tracked, inliers, map, keyframes, segment, dropped, skipped (with the
   `busy / rate / buffer / no-frame` breakdown), fps, twin updates, lost
   episodes, `sending W×H → tracked at w×h`, intrinsics. A second screenshot
   at ~5 s is a bonus.
2. **uvicorn lines** for the session: the `WebSocket /live/<id> [accepted]`
   line, every `GET /live/<id>/cloud`, any `Error` / `Traceback`, the
   `Classifications: {...}` line and `GET /sessions/<id>/twin … 200`.
3. **`outputs/<id>/tracking_report.json`** from the PC (frames, keyframes,
   state_counts, lost_episodes, map_size, timing) and
   `outputs/<id>/run_status.json` (`live.dropped`, `live.source_size`).
4. **P2 plane count and labels** of the finished session (sidebar → Inspect,
   or `curl http://192.168.1.37:8000/sessions/<id>/room_model | jq '.planes[] | {id,type,support}'`),
   and of the first twin update that drew geometry if you noticed it.
5. **A screenshot of the session view** after the hand-off (3D twin, Room
   Measurements, provenance footer — or the no-geometry notice).
6. Phone model, Android version, whether the camera prompt appeared, whether
   the Backend probe said ok at first try, and how it felt: did the banner
   match what you were doing (LOST when you swung, TRACKING when you walked)?
   If you also tried the file source: which clip (H.264 `.mp4` / VP8
   `.webm`) and whether it played.
