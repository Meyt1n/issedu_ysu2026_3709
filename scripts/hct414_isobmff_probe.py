"""Minimal ISO-BMFF (MP4/MOV) container probe: brand, tracks, codec fourcc, timing.

No external dependencies. Reads only box headers and the few leaf boxes needed for
container/encoding evidence. Never decodes or emits media content.
"""

from __future__ import annotations

import hashlib
import json
import struct
import sys
from pathlib import Path

CONTAINERS = {b"moov", b"trak", b"mdia", b"minf", b"stbl", b"edts", b"udta"}


def iter_boxes(buf: bytes, start: int, end: int):
    pos = start
    while pos + 8 <= end:
        size = struct.unpack_from(">I", buf, pos)[0]
        btype = buf[pos + 4 : pos + 8]
        header = 8
        if size == 1:
            size = struct.unpack_from(">Q", buf, pos + 8)[0]
            header = 16
        elif size == 0:
            size = end - pos
        if size < header or pos + size > end:
            break
        yield btype, pos + header, pos + size
        pos += size


def parse_ftyp(buf, s, e):
    major = buf[s : s + 4].decode("latin-1")
    minor = struct.unpack_from(">I", buf, s + 4)[0]
    compat = [buf[i : i + 4].decode("latin-1") for i in range(s + 8, e, 4)]
    return {"major_brand": major, "minor_version": minor, "compatible_brands": compat}


def parse_mvhd(buf, s, _e):
    ver = buf[s]
    off = s + 4
    if ver == 1:
        timescale = struct.unpack_from(">I", buf, off + 16)[0]
        duration = struct.unpack_from(">Q", buf, off + 20)[0]
    else:
        timescale = struct.unpack_from(">I", buf, off + 8)[0]
        duration = struct.unpack_from(">I", buf, off + 12)[0]
    return {"timescale": timescale, "duration": duration}


def parse_tkhd(buf, s, _e):
    """tkhd payload: version+flags(4), then times/id/duration, then matrix, width, height."""
    ver = buf[s]
    p = s + 4
    if ver == 1:
        tid = struct.unpack_from(">I", buf, p + 16)[0]
        w_off, h_off = p + 80, p + 84
    else:
        tid = struct.unpack_from(">I", buf, p + 8)[0]
        w_off, h_off = p + 72, p + 76
    w = struct.unpack_from(">I", buf, w_off)[0] / 65536.0
    h = struct.unpack_from(">I", buf, h_off)[0] / 65536.0
    return {"track_id": tid, "width": round(w, 2), "height": round(h, 2)}


def parse_mdhd(buf, s, _e):
    ver = buf[s]
    off = s + 4
    if ver == 1:
        timescale = struct.unpack_from(">I", buf, off + 16)[0]
        duration = struct.unpack_from(">Q", buf, off + 20)[0]
    else:
        timescale = struct.unpack_from(">I", buf, off + 8)[0]
        duration = struct.unpack_from(">I", buf, off + 12)[0]
    return {"timescale": timescale, "duration": duration}


def parse_stsd(buf, s, e):
    count = struct.unpack_from(">I", buf, s + 4)[0]
    entries = []
    for btype, bs, be in iter_boxes(buf, s + 8, e):
        entry = {"format": btype.decode("latin-1")}
        if btype in (b"avc1", b"avc3", b"hvc1", b"hev1", b"av01", b"vp09"):
            entry["width"] = struct.unpack_from(">H", buf, bs + 24)[0]
            entry["height"] = struct.unpack_from(">H", buf, bs + 26)[0]
            for sub, ss, _se in iter_boxes(buf, bs + 78, be):
                if sub == b"avcC":
                    entry["avc_profile"] = buf[ss + 1]
                    entry["avc_level"] = buf[ss + 3]
                elif sub == b"hvcC":
                    entry["hevc_profile"] = buf[ss + 1] & 0x1F
        elif btype in (b"mp4a", b"twos", b".mp3"):
            entry["channels"] = struct.unpack_from(">H", buf, bs + 16)[0]
            entry["sample_rate"] = struct.unpack_from(">I", buf, bs + 24)[0] >> 16
        entries.append(entry)
        if len(entries) >= count:
            break
    return entries


def walk(buf, s, e, out, trak=None):
    for btype, bs, be in iter_boxes(buf, s, e):
        if btype == b"ftyp":
            out["ftyp"] = parse_ftyp(buf, bs, be)
        elif btype == b"mvhd":
            out["mvhd"] = parse_mvhd(buf, bs, be)
        elif btype == b"trak":
            trak = {}
            out.setdefault("tracks", []).append(trak)
            walk(buf, bs, be, out, trak)
        elif btype == b"tkhd" and trak is not None:
            trak.update(parse_tkhd(buf, bs, be))
        elif btype == b"mdhd" and trak is not None:
            trak["mdhd"] = parse_mdhd(buf, bs, be)
        elif btype == b"hdlr" and trak is not None:
            trak["handler"] = buf[bs + 8 : bs + 12].decode("latin-1")
        elif btype == b"stsd" and trak is not None:
            trak["sample_entries"] = parse_stsd(buf, bs, be)
        elif btype == b"stsz" and trak is not None:
            trak["sample_count"] = struct.unpack_from(">I", buf, bs + 8)[0]
        elif btype in CONTAINERS:
            walk(buf, bs, be, out, trak)
        else:
            out.setdefault("top_level_boxes", [])
            if s == 0:
                out["top_level_boxes"].append(btype.decode("latin-1"))


def probe(path: Path) -> dict:
    buf = path.read_bytes()
    out: dict = {
        "file_name": path.name,
        "size_bytes": len(buf),
        "sha256": hashlib.sha256(buf).hexdigest(),
    }
    walk(buf, 0, len(buf), out)
    mv = out.get("mvhd") or {}
    if mv.get("timescale"):
        out["duration_seconds"] = round(mv["duration"] / mv["timescale"], 3)
        if out["duration_seconds"]:
            out["overall_bitrate_bps"] = int(len(buf) * 8 / out["duration_seconds"])
    for t in out.get("tracks", []):
        md = t.get("mdhd") or {}
        if md.get("timescale"):
            t["duration_seconds"] = round(md["duration"] / md["timescale"], 3)
            if t.get("sample_count") and t["duration_seconds"]:
                t["samples_per_second"] = round(t["sample_count"] / t["duration_seconds"], 2)
    return out


if __name__ == "__main__":
    for arg in sys.argv[1:]:
        print(json.dumps(probe(Path(arg)), ensure_ascii=False, indent=2))
