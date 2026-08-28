"""Drive the on-device WebView over CDP to test the MOB-149 video input path.

Injects a real device-produced MP4 into the live WebView, reconstructs a File the way
the file picker would, then runs the same allowlist + <video> metadata probe the app
uses (APP/src/utils/videoInput.ts). Read-only: no app code or app state is modified.
"""

from __future__ import annotations

import asyncio
import base64
import json
import sys
from pathlib import Path

import websockets

CHUNK = 96 * 1024


async def call(ws, mid, method, params=None):
    await ws.send(json.dumps({"id": mid, "method": method, "params": params or {}}))
    while True:
        msg = json.loads(await ws.recv())
        if msg.get("id") == mid:
            return msg


async def ev(ws, mid, expr, await_promise=False):
    r = await call(
        ws,
        mid,
        "Runtime.evaluate",
        {"expression": expr, "returnByValue": True, "awaitPromise": await_promise},
    )
    res = r.get("result", {})
    if "exceptionDetails" in res:
        details = res["exceptionDetails"]
        return {
            "__error__": details.get("text"),
            "detail": str(details.get("exception")),
        }
    return res.get("result", {}).get("value")


CAPS_JS = r"""
(async () => {
  const mr = t => {
    try { return MediaRecorder.isTypeSupported(t) } catch (e) { return 'no MediaRecorder' }
  };
  const ms = t => {
    try { return MediaSource.isTypeSupported(t) } catch (e) { return 'no MediaSource' }
  };
  const v = document.createElement('video');
  const types = ['video/mp4','video/mp4; codecs="avc1.640028"','video/mp4; codecs="hvc1"',
                 'video/mp4; codecs="hvc1.1.6.L93.B0"','video/mp4; codecs="hev1.1.6.L93.B0"',
                 'video/quicktime','video/x-quicktime','video/webm','video/webm; codecs="vp8"',
                 'video/webm; codecs="vp9"'];
  const out = {
    userAgent: navigator.userAgent,
    canPlayType: {}, mediaRecorder: {}, mediaSource: {}, decodingInfo: {},
  };
  for (const t of types) {
    out.canPlayType[t] = v.canPlayType(t) || '(empty = not supported)';
    out.mediaRecorder[t] = mr(t);
    out.mediaSource[t] = ms(t);
  }
  // Authoritative decode capability for the real camera profile measured on this device.
  const probes = {
    'camera HEVC 1080p30 15.3Mbps': 'video/mp4; codecs="hvc1.1.6.L93.B0"',
    'screenrecord AVC High 4.2 720p60': 'video/mp4; codecs="avc1.640028"',
  };
  for (const [label, contentType] of Object.entries(probes)) {
    try {
      const info = await navigator.mediaCapabilities.decodingInfo({
        type: 'file',
        video: { contentType, width: 1920, height: 1080, bitrate: 15340000, framerate: 30 },
      });
      out.decodingInfo[label] = {
        contentType,
        supported: info.supported,
        smooth: info.smooth,
        powerEfficient: info.powerEfficient,
      };
    } catch (e) {
      out.decodingInfo[label] = { contentType, error: String(e) };
    }
  }
  out.hasFileInput = (() => {
    const i = document.createElement('input');
    i.type = 'file';
    return i.type === 'file';
  })();
  out.captureAttrSupported = 'capture' in document.createElement('input');
  return out;
})()
"""

PROBE_JS = r"""
(async () => {
  const bin = atob(window.__hct414_b64);
  const buf = new Uint8Array(bin.length);
  for (let i = 0; i < bin.length; i++) buf[i] = bin.charCodeAt(i);
  const results = [];
  const ALLOWED_EXT = ['.mp4', '.mov'];
  const ALLOWED_MIME = ['video/mp4', 'video/quicktime', 'video/x-quicktime'];
  const cases = [
    { name: 'device_clip.mp4', type: 'video/mp4' },
    { name: 'device_clip.mov', type: 'video/quicktime' },
    { name: 'device_clip.mp4', type: '' },
    { name: 'device_clip.3gp', type: 'video/3gpp' },
  ];
  for (const c of cases) {
    const file = new File([buf], c.name, { type: c.type });
    const lower = file.name.toLowerCase();
    const ext = lower.slice(lower.lastIndexOf('.'));
    const probe = await new Promise(resolve => {
      const url = URL.createObjectURL(file);
      const el = document.createElement('video');
      el.preload = 'metadata'; el.muted = true;
      const done = p => { clearTimeout(t); el.removeAttribute('src'); URL.revokeObjectURL(url);
                          resolve(p || { durationSeconds: 0, width: 0, height: 0 }) };
      const t = setTimeout(() => done(null), 5000);
      el.onloadedmetadata = () => done({
        durationSeconds: Number.isFinite(el.duration) ? el.duration : 0,
        width: el.videoWidth || 0,
        height: el.videoHeight || 0,
      });
      el.onerror = () => done(null);
      el.src = url;
    });
    results.push({
      declared_name: c.name, declared_type: c.type || '(empty)',
      reported_file_type: file.type || '(empty)', reported_size: file.size,
      extension_allowed: ALLOWED_EXT.includes(ext),
      mime_allowed: ALLOWED_MIME.includes(file.type),
      probe,
      probe_ok: probe.durationSeconds > 0 && probe.width > 0 && probe.height > 0,
    });
  }
  return results;
})()
"""


async def main(ws_url: str, mp4: Path):
    b64 = base64.b64encode(mp4.read_bytes()).decode()
    async with websockets.connect(ws_url, max_size=64 * 1024 * 1024) as ws:
        mid = 0
        mid += 1
        await call(ws, mid, "Runtime.enable")

        mid += 1
        caps = await ev(ws, mid, CAPS_JS, await_promise=True)

        mid += 1
        await ev(ws, mid, "window.__hct414_b64 = ''; 'reset'")
        for i in range(0, len(b64), CHUNK):
            mid += 1
            part = b64[i : i + CHUNK]
            expr = f"window.__hct414_b64 += {json.dumps(part)}; window.__hct414_b64.length"
            await ev(ws, mid, expr)
        mid += 1
        injected = await ev(ws, mid, "window.__hct414_b64.length")

        mid += 1
        probes = await ev(ws, mid, PROBE_JS, await_promise=True)

        mid += 1
        await ev(ws, mid, "delete window.__hct414_b64; 'cleaned'")

        print(json.dumps(
            {"webview": caps, "injected_base64_chars": injected,
             "expected_base64_chars": len(b64), "cases": probes},
            ensure_ascii=False, indent=2))


if __name__ == "__main__":
    asyncio.run(main(sys.argv[1], Path(sys.argv[2])))
