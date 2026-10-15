"""Desktop verification of the Live screen in a real Chrome, driven over the
DevTools Protocol (no extension needed): opens /#/live on the Vite dev server,
picks the given source, starts, logs the status strip every second, stops,
and checks the hand-off to the session view. Screenshots go to --out.

    python scripts/drive_live_ui.py --video data/input/synthetic_box_room_30fps_h264.mp4 --out outputs/live_ui
    python scripts/drive_live_ui.py --camera --out outputs/live_ui_cam   # Chrome's fake camera device

Requires Chrome and the `websockets` package. Prints what it observed; it
never fakes a result (a missing canvas or a stuck state is reported as such).
"""
import argparse
import asyncio
import base64
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.request
from pathlib import Path

import websockets

CHROME = r"C:\Program Files\Google\Chrome\Application\chrome.exe"
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")  # the status strip contains "→" / "×"


class CDP:
    def __init__(self, ws):
        self.ws = ws
        self.next_id = 1
        self.pending = {}
        self.console = []
        self.errors = []

    async def pump(self):
        async for raw in self.ws:
            msg = json.loads(raw)
            if "id" in msg:
                fut = self.pending.pop(msg["id"], None)
                if fut:
                    fut.set_result(msg)
            elif msg.get("method") == "Runtime.consoleAPICalled":
                p = msg["params"]
                text = " ".join(str(a.get("value", a.get("description", ""))) for a in p.get("args", []))
                self.console.append((p["type"], text))
            elif msg.get("method") == "Runtime.exceptionThrown":
                self.errors.append(msg["params"]["exceptionDetails"].get("text", "") + " " +
                                   str(msg["params"]["exceptionDetails"].get("exception", {}).get("description", "")))

    async def call(self, method, **params):
        mid = self.next_id
        self.next_id += 1
        fut = asyncio.get_running_loop().create_future()
        self.pending[mid] = fut
        await self.ws.send(json.dumps({"id": mid, "method": method, "params": params}))
        res = await asyncio.wait_for(fut, 30)
        if "error" in res:
            raise RuntimeError(f"{method}: {res['error']}")
        return res.get("result", {})

    async def js(self, expr):
        res = await self.call("Runtime.evaluate", expression=expr, returnByValue=True, awaitPromise=True)
        if "exceptionDetails" in res:
            raise RuntimeError(res["exceptionDetails"].get("text"))
        return res.get("result", {}).get("value")

    async def screenshot(self, path):
        res = await self.call("Page.captureScreenshot", format="png")
        Path(path).write_bytes(base64.b64decode(res["data"]))


STATUS_JS = """(() => {
  const t = (sel) => (document.querySelector(sel)?.textContent || '').trim().replace(/\\s+/g, ' ');
  return {
    state: t('.live-state').split(' ')[0],
    strip: t('.live-status-strip'),
    placeholder: t('.live-placeholder'),
    canvas: !!document.querySelector('.live-viewer canvas'),
    error: t('.error'),
    hash: location.hash,
    finished: t('.live-screen > p.muted'),
  };
})()"""


async def run(args):
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    profile = tempfile.mkdtemp(prefix="vf_chrome_")
    port = 9333
    flags = [CHROME, f"--remote-debugging-port={port}", f"--user-data-dir={profile}", "--no-first-run",
             "--no-default-browser-check", "--window-size=1400,1000", "--use-fake-ui-for-media-stream",
             "--use-fake-device-for-media-stream", "--autoplay-policy=no-user-gesture-required",
             "--enable-unsafe-swiftshader", "--use-gl=angle", "--use-angle=swiftshader"]
    if not args.headed:
        flags.append("--headless=new")
    flags.append("about:blank")
    chrome = subprocess.Popen(flags, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        for _ in range(50):
            try:
                targets = json.loads(urllib.request.urlopen(f"http://127.0.0.1:{port}/json").read())
                page = next(t for t in targets if t["type"] == "page")
                break
            except Exception:
                time.sleep(0.2)
        else:
            sys.exit("Chrome did not expose a page target")
        async with websockets.connect(page["webSocketDebuggerUrl"], max_size=None) as ws:
            cdp = CDP(ws)
            pump = asyncio.create_task(cdp.pump())
            await cdp.call("Page.enable")
            await cdp.call("Runtime.enable")
            await cdp.call("Page.navigate", url=args.url)
            await asyncio.sleep(2.5)
            print("title:", await cdp.js("document.title"), "| hash:", await cdp.js("location.hash"))
            await cdp.screenshot(out / "01_live_idle.png")

            if args.camera:
                print("source: camera (Chrome fake device)")
            else:
                # React-controlled <select>: set through the native setter so React sees the change
                await cdp.js("""(() => { const s = document.querySelector('.live-controls select');
                    Object.getOwnPropertyDescriptor(HTMLSelectElement.prototype, 'value').set.call(s, 'file');
                    s.dispatchEvent(new Event('change', { bubbles: true })); return s.value; })()""")
                doc = await cdp.call("DOM.getDocument")
                node = await cdp.call("DOM.querySelector", nodeId=doc["root"]["nodeId"], selector="input[type=file]")
                await cdp.call("DOM.setFileInputFiles", files=[str(Path(args.video).resolve())], nodeId=node["nodeId"])
                print("source: file", args.video)
            await asyncio.sleep(0.5)
            await cdp.js("document.querySelector('button.primary').click()")
            t0 = time.time()
            seen_states = []
            first_canvas_at = None
            last = None
            for i in range(args.seconds):
                await asyncio.sleep(1.0)
                st = await cdp.js(STATUS_JS)
                last = st
                if not seen_states or seen_states[-1] != st["state"]:
                    seen_states.append(st["state"])
                if st["canvas"] and first_canvas_at is None:
                    first_canvas_at = round(time.time() - t0, 1)
                    await cdp.screenshot(out / "02_first_twin_drawn.png")
                print(f"t={i + 1:2d}s {st['state']:12s} canvas={st['canvas']!s:5s} | {st['strip']} | {st['placeholder']} {('ERR: ' + st['error']) if st['error'] else ''}")
                if st["error"] and "Could not start" in st["error"]:
                    break
                if st["state"] == "TRACKING" and st["canvas"] and i >= args.min_seconds:
                    break
            await cdp.screenshot(out / "03_before_stop.png")
            await cdp.js("document.querySelector('button.danger') && document.querySelector('button.danger').click()")
            print("clicked Stop; waiting for the finished reply / navigation...")
            nav = None
            for _ in range(60):
                await asyncio.sleep(0.5)
                h = await cdp.js("location.hash")
                if h.startswith("#/session/"):
                    nav = h
                    break
            print("hash after finish:", nav)
            await asyncio.sleep(3.0)
            session_view = await cdp.js("""(() => ({
                hash: location.hash,
                sessions: [...document.querySelectorAll('.session-list .session-id')].map(e => e.textContent),
                selected: document.querySelector('.session-list .session.selected .session-id')?.textContent || null,
                canvas: !!document.querySelector('.viewer canvas'),
                measurements: (document.querySelector('.kv')?.textContent || '').trim().replace(/\\s+/g, ' ').slice(0, 200),
                error: (document.querySelector('.error')?.textContent || '').trim(),
            }))()""")
            await cdp.screenshot(out / "04_session_view.png")
            print("session view:", json.dumps(session_view))
            print("states seen:", seen_states, "| first viewer canvas at", first_canvas_at, "s")
            print("console errors:", [e for e in cdp.errors][:5])
            print("console (error level):", [t for lvl, t in cdp.console if lvl == "error"][:5])
            pump.cancel()
            return last, session_view
    finally:
        chrome.terminate()
        try:
            chrome.wait(5)
        except subprocess.TimeoutExpired:
            chrome.kill()
        shutil.rmtree(profile, ignore_errors=True)


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--url", default="http://localhost:5173/#/live")
    p.add_argument("--video", default=None)
    p.add_argument("--camera", action="store_true")
    p.add_argument("--out", default="outputs/live_ui")
    p.add_argument("--seconds", type=int, default=40, help="max seconds to run before stopping")
    p.add_argument("--min-seconds", type=int, default=15)
    p.add_argument("--headed", action="store_true")
    args = p.parse_args()
    if not args.camera and not args.video:
        sys.exit("--video or --camera")
    asyncio.run(run(args))


if __name__ == "__main__":
    main()
