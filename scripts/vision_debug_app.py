"""Local vision debug page: YOLO boxes + OCR tokens rendered in the browser.

Teaching-demo tool for the family trusted domain. It runs the same isolated
engine workers as the adapter (YOLO box-assist, PaddleOCR full-image-first,
OpenCV barcode, rule field candidates) on an uploaded image and renders the
raw evidence — nothing is persisted, no health event is written, and the
LLM stays untouched (results here are recognition evidence, not facts).

Run (repo root; workers need the adapter env that has paddle/torch):

    $env:HCT_VISION_WEIGHTS = "<仓库外的 YOLO 权重>\best.pt"
    $env:HCT_VISION_WORKER_PYTHON = "<你的 PaddleOCR 环境>\python.exe"
    uv run python scripts/vision_debug_app.py --port 18901
"""
# ruff: noqa: E501  (embedded HTML/CSS/JS page)

from __future__ import annotations

import argparse
import base64
import sys
import tempfile
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
for entry in (REPO_ROOT / "src", REPO_ROOT / "src" / "api"):
    if str(entry) not in sys.path:
        sys.path.insert(0, str(entry))

import uvicorn  # noqa: E402
from ai.vision.local_models import QwenLoraFieldExtractor, YoloBoxAssist  # noqa: E402
from ai.vision.local_ocr import (  # noqa: E402
    LocalBarcodeDecoder,
    LocalPaddleOCR,
    _read_image_bgr,
)
from ai.vision.rule_fields import propose_fields  # noqa: E402
from fastapi import FastAPI, File, UploadFile  # noqa: E402
from fastapi.responses import HTMLResponse, JSONResponse  # noqa: E402

app = FastAPI(title="HomeCare Twin 视觉调试页（教学演示）", docs_url=None, redoc_url=None)

MAX_UPLOAD_BYTES = 15 * 1024 * 1024
ALLOWED_SUFFIXES = {".jpg", ".jpeg", ".png", ".webp", ".bmp"}


def region_dict(region) -> dict | None:
    if region is None:
        return None
    return {
        "x": region.x,
        "y": region.y,
        "width": region.width,
        "height": region.height,
    }


@app.get("/", response_class=HTMLResponse)
def index() -> str:
    return PAGE


@app.post("/api/analyze")
async def analyze(file: UploadFile = File(...)) -> JSONResponse:
    suffix = Path(file.filename or "upload.png").suffix.lower()
    if suffix not in ALLOWED_SUFFIXES:
        return JSONResponse({"error": f"不支持的文件类型：{suffix}"}, status_code=422)
    content = await file.read()
    if not content or len(content) > MAX_UPLOAD_BYTES:
        return JSONResponse({"error": "文件为空或超过 15MB 限制"}, status_code=422)

    with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as handle:
        handle.write(content)
        temp_path = Path(handle.name)

    try:
        image = _read_image_bgr(temp_path)
        if image is None:
            return JSONResponse({"error": "图片无法解码"}, status_code=422)
        height, width = image.shape[:2]

        quality: dict = {"decision": "SKIPPED", "reasons": []}
        try:
            from ai.vision.quality_gate import assess_image

            verdict = assess_image(image, source_id=file.filename or "upload")
            quality = {
                "decision": verdict.get("decision", "UNKNOWN"),
                "reasons": list(verdict.get("reasons", [])),
                "retake_prompts": list(verdict.get("retake_prompts", [])),
            }
        except Exception as exc:  # gate stays informational in the debug page
            quality = {"decision": "UNAVAILABLE", "reasons": [str(exc)[:200]]}

        yolo = YoloBoxAssist()
        started = time.monotonic()
        proposals = yolo.propose_regions(temp_path)
        yolo_ms = int((time.monotonic() - started) * 1000)

        ocr = LocalPaddleOCR()
        started = time.monotonic()
        tokens = ocr.recognize(temp_path, proposals)
        ocr_ms = int((time.monotonic() - started) * 1000)

        decoder = LocalBarcodeDecoder()
        barcodes = decoder.decode(temp_path)

        subtokens, field_proposals = propose_fields(tokens, barcodes, proposals)
        all_tokens = tokens + subtokens

        extractor = QwenLoraFieldExtractor()

        payload = {
            "note": "教学演示：以下均为识别证据，不构成药品身份或健康事实，未写入任何数据库。",
            "image": {
                "data_url": "data:image/png;base64,"
                + base64.b64encode(content).decode("ascii")
                if suffix == ".png"
                else "data:image/jpeg;base64,"
                + base64.b64encode(content).decode("ascii"),
                "width": width,
                "height": height,
                "name": file.filename,
            },
            "quality": quality,
            "yolo": {
                "available": yolo.available,
                "version": yolo.model_version,
                "elapsed_ms": yolo_ms,
                "degraded": yolo.available and not proposals,
                "boxes": [
                    {
                        "id": proposal.id,
                        "label": proposal.label,
                        "confidence": proposal.confidence,
                        "region": region_dict(proposal.region),
                    }
                    for proposal in proposals
                ],
            },
            "ocr": {
                "available": ocr.available,
                "version": ocr.engine_version if ocr.available else "unavailable",
                "elapsed_ms": ocr_ms,
                "tokens": [
                    {
                        "id": token.id,
                        "text": token.raw_value,
                        "confidence": token.confidence,
                        "region": region_dict(token.region),
                        "derived": "-f" in token.id,
                    }
                    for token in all_tokens
                ],
            },
            "barcode": {
                "available": decoder.available,
                "candidates": [
                    {
                        "id": candidate.id,
                        "value": candidate.raw_value,
                        "format": candidate.format,
                        "checksum_valid": candidate.checksum_valid,
                        "region": region_dict(candidate.region),
                    }
                    for candidate in barcodes
                ],
            },
            "fields": [
                {
                    "field": proposal.field_name,
                    "value": proposal.raw_value,
                    "source": proposal.source,
                    "confidence": proposal.confidence,
                    "evidence_ids": proposal.evidence_ids,
                }
                for proposal in field_proposals
            ],
            "llm": {
                "available": extractor.available,
                "note": "LLM 槽位归类当前未启用（GPU 训练中），字段候选来自确定性规则层。"
                if not extractor.available
                else "LLM 已配置。",
            },
        }
        return JSONResponse(payload)
    finally:
        temp_path.unlink(missing_ok=True)


PAGE = """<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<title>视觉调试页 · 家健镜（教学演示）</title>
<meta name="viewport" content="width=device-width, initial-scale=1">
<style>
:root { --ink:#1c2b26; --line:#d8d2c5; --accent:#2e6e4e; --blue:#1565c0; --amber:#b3541e; }
* { box-sizing:border-box; }
body { margin:0; font-family:"Microsoft YaHei",system-ui,sans-serif; background:#f6f2e9; color:var(--ink); }
header { padding:14px 22px; background:#fffdf7; border-bottom:1px solid var(--line); display:flex; gap:14px; align-items:baseline; flex-wrap:wrap; }
header h1 { font-size:18px; margin:0; }
header .demo { font-size:12px; color:#8a6d3b; background:#fcf3d9; border:1px solid #ecd9a6; border-radius:99px; padding:2px 10px; }
main { display:grid; grid-template-columns: minmax(0,1fr) 380px; gap:16px; padding:16px 22px; align-items:start; }
@media (max-width: 980px) { main { grid-template-columns:1fr; } }
.card { background:#fffdf7; border:1px solid var(--line); border-radius:14px; padding:14px; }
#drop { border:2px dashed #b9ae97; border-radius:14px; padding:26px; text-align:center; cursor:pointer; transition:.15s; }
#drop.hover { border-color:var(--accent); background:#eef4ee; }
#stage { position:relative; margin-top:12px; display:none; }
#stage canvas { width:100%; height:auto; border-radius:10px; display:block; }
.toggles { display:flex; gap:14px; margin-top:10px; font-size:13px; flex-wrap:wrap; }
.chips { display:flex; gap:8px; flex-wrap:wrap; margin:6px 0 2px; }
.chip { font-size:12px; border-radius:99px; padding:3px 10px; border:1px solid var(--line); background:#fff; }
.chip.ok { border-color:#9ec5ab; background:#eef7ef; color:#20613f; }
.chip.warn { border-color:#e7c589; background:#fdf4e0; color:#8a5a19; }
.chip.err { border-color:#e5a9a1; background:#fdeeec; color:#93392c; }
h2 { font-size:14px; margin:4px 0 8px; }
table { width:100%; border-collapse:collapse; font-size:13px; }
th, td { text-align:left; padding:6px 8px; border-bottom:1px solid #eee5d4; vertical-align:top; word-break:break-all; }
th { color:#6e6353; font-weight:600; }
.conf { font-variant-numeric:tabular-nums; color:#6e6353; }
.tok-derived { color:#8a6d3b; font-size:11px; }
#spin { display:none; margin-top:12px; font-size:13px; color:#6e6353; }
#spin.on { display:block; }
.legend { font-size:12px; color:#6e6353; margin-top:8px; }
.legend b.y { color:#12a150; } .legend b.o { color:var(--blue); } .legend b.b { color:var(--amber); }
button.primary { background:var(--accent); color:#fff; border:none; border-radius:10px; padding:8px 16px; font-size:14px; cursor:pointer; }
</style>
</head>
<body>
<header>
  <h1>视觉调试页 · YOLO 定位 + OCR 识别</h1>
  <span class="demo">教学演示 · 本地运行 · 结果不入库 · 非诊断</span>
</header>
<main>
  <section class="card">
    <div id="drop">
      <p><b>点击选择</b> 或把药盒图片拖到这里（jpg/png，≤15MB）</p>
      <p style="font-size:12px;color:#6e6353">每次识别约 15–60 秒：OCR/YOLO 在受限内存下按需启动隔离进程</p>
      <input id="file" type="file" accept="image/*" hidden>
    </div>
    <div id="spin">正在识别（YOLO 定位 → PaddleOCR 全图+裁剪 → 条码 → 规则字段候选）……</div>
    <div id="stage"><canvas id="canvas"></canvas>
      <div class="toggles">
        <label><input type="checkbox" id="tgYolo" checked> YOLO 定位框（绿）</label>
        <label><input type="checkbox" id="tgOcr" checked> OCR 文本框（蓝）</label>
        <label><input type="checkbox" id="tgText" checked> 识别文字标签</label>
        <label><input type="checkbox" id="tgBar" checked> 条码（橙）</label>
      </div>
      <div class="legend">图例：<b class="y">■ YOLO 药盒定位</b> · <b class="o">■ OCR 文本区域</b> · <b class="b">■ 条码/二维码</b>；OCR 是文字主来源，YOLO 只做定位辅助，两者互不覆盖。</div>
    </div>
  </section>
  <aside style="display:flex;flex-direction:column;gap:14px;">
    <section class="card" id="status" style="display:none">
      <h2>引擎状态</h2>
      <div class="chips" id="chips"></div>
      <div id="quality" style="font-size:13px;margin-top:6px"></div>
    </section>
    <section class="card" id="fieldsCard" style="display:none">
      <h2>字段候选（全部待人工确认）</h2>
      <table id="fields"><thead><tr><th>字段</th><th>值</th><th>来源</th><th class="conf">置信</th></tr></thead><tbody></tbody></table>
    </section>
    <section class="card" id="tokensCard" style="display:none">
      <h2>OCR 识别结果</h2>
      <table id="tokens"><thead><tr><th>文本</th><th class="conf">置信</th></tr></thead><tbody></tbody></table>
    </section>
  </aside>
</main>
<script>
const drop = document.getElementById('drop');
const fileInput = document.getElementById('file');
const spin = document.getElementById('spin');
const stage = document.getElementById('stage');
const canvas = document.getElementById('canvas');
const ctx = canvas.getContext('2d');
let data = null, img = new Image();

drop.onclick = () => fileInput.click();
['dragover','dragenter'].forEach(ev => drop.addEventListener(ev, e => { e.preventDefault(); drop.classList.add('hover'); }));
['dragleave','drop'].forEach(ev => drop.addEventListener(ev, e => { e.preventDefault(); drop.classList.remove('hover'); }));
drop.addEventListener('drop', e => { if (e.dataTransfer.files[0]) send(e.dataTransfer.files[0]); });
fileInput.onchange = () => { if (fileInput.files[0]) send(fileInput.files[0]); };
for (const id of ['tgYolo','tgOcr','tgText','tgBar']) document.getElementById(id).onchange = draw;

async function send(file) {
  spin.classList.add('on'); stage.style.display = 'none';
  const body = new FormData(); body.append('file', file);
  try {
    const res = await fetch('/api/analyze', { method: 'POST', body });
    const json = await res.json();
    if (!res.ok) throw new Error(json.error || res.status);
    data = json;
    img = new Image();
    img.onload = () => { render(); };
    img.src = json.image.data_url;
  } catch (err) {
    alert('识别失败：' + err.message);
  } finally { spin.classList.remove('on'); }
}

function chip(label, cls) { return `<span class="chip ${cls}">${label}</span>`; }

function render() {
  stage.style.display = 'block';
  document.getElementById('status').style.display = 'block';
  const chips = [];
  const y = data.yolo;
  chips.push(y.available ? (y.boxes.length ? chip(`YOLO ✓ ${y.boxes.length} 框 · ${y.elapsed_ms}ms`, 'ok') : chip('YOLO 降级（无检出/资源不足）', 'warn')) : chip('YOLO 未配置', 'err'));
  const o = data.ocr;
  chips.push(o.available ? chip(`OCR ✓ ${o.tokens.filter(t=>!t.derived).length} 行 · ${(o.elapsed_ms/1000).toFixed(1)}s`, 'ok') : chip('OCR 不可用', 'err'));
  chips.push(data.barcode.candidates.length ? chip(`条码 ✓ ${data.barcode.candidates.length}`, 'ok') : chip('条码：无', 'warn'));
  chips.push(data.llm.available ? chip('LLM 已配置', 'ok') : chip('LLM 暂停（训练中）→ 规则候选', 'warn'));
  document.getElementById('chips').innerHTML = chips.join('');
  const q = data.quality;
  document.getElementById('quality').innerHTML =
    `质量门控：<b>${q.decision}</b>${q.reasons && q.reasons.length ? ' · ' + q.reasons.join('、') : ''}<br><span style="color:#6e6353">${data.note}</span>`;

  const ftb = document.querySelector('#fields tbody'); ftb.innerHTML = '';
  const NAMES = {drug_name:'药名', specification:'规格', manufacturer:'厂家', batch_number:'批号', expiry_date:'有效期', product_barcode:'条码/追溯码', packaging_type:'包装类型'};
  for (const f of data.fields) {
    ftb.insertAdjacentHTML('beforeend',
      `<tr><td>${NAMES[f.field] || f.field}</td><td>${f.value}</td><td>${f.source}</td><td class="conf">${f.confidence.toFixed(2)}</td></tr>`);
  }
  document.getElementById('fieldsCard').style.display = data.fields.length ? 'block' : 'none';

  const ttb = document.querySelector('#tokens tbody'); ttb.innerHTML = '';
  for (const t of data.ocr.tokens) {
    ttb.insertAdjacentHTML('beforeend',
      `<tr><td>${t.text}${t.derived ? ' <span class="tok-derived">（规则子串）</span>' : ''}</td><td class="conf">${t.confidence.toFixed(2)}</td></tr>`);
  }
  document.getElementById('tokensCard').style.display = data.ocr.tokens.length ? 'block' : 'none';
  draw();
}

function draw() {
  if (!data || !img.width) return;
  canvas.width = img.width; canvas.height = img.height;
  ctx.drawImage(img, 0, 0);
  const scale = Math.max(1, Math.round(img.width / 640));
  if (document.getElementById('tgYolo').checked) {
    for (const b of data.yolo.boxes) {
      const r = b.region; if (!r) continue;
      ctx.strokeStyle = '#12a150'; ctx.lineWidth = 3 * scale;
      ctx.strokeRect(r.x, r.y, r.width, r.height);
      label(`药盒 ${b.confidence.toFixed(2)}`, r.x, Math.max(r.y - 8 * scale, 14 * scale), '#12a150', scale);
    }
  }
  if (document.getElementById('tgOcr').checked) {
    for (const t of data.ocr.tokens) {
      if (t.derived) continue;
      const r = t.region; if (!r) continue;
      ctx.strokeStyle = '#1565c0'; ctx.lineWidth = 1.5 * scale;
      ctx.strokeRect(r.x, r.y, r.width, r.height);
      if (document.getElementById('tgText').checked) {
        label(`${t.text} ${t.confidence.toFixed(2)}`, r.x, r.y + r.height + 16 * scale, '#1565c0', scale);
      }
    }
  }
  if (document.getElementById('tgBar').checked) {
    for (const c of data.barcode.candidates) {
      const r = c.region; if (!r) continue;
      ctx.strokeStyle = '#b3541e'; ctx.lineWidth = 2 * scale;
      ctx.strokeRect(r.x, r.y, r.width, r.height);
      label(`${c.format} ${c.value}`, r.x, Math.max(r.y - 8 * scale, 14 * scale), '#b3541e', scale);
    }
  }
}

function label(text, x, y, color, scale) {
  ctx.font = `${12 * scale}px "Microsoft YaHei", sans-serif`;
  const w = ctx.measureText(text).width;
  ctx.fillStyle = 'rgba(255,255,255,0.88)';
  ctx.fillRect(x - 2, y - 12 * scale, w + 8, 15 * scale);
  ctx.fillStyle = color;
  ctx.fillText(text, x + 2, y);
}
</script>
</body>
</html>
"""


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=18901)
    args = parser.parse_args()
    uvicorn.run(app, host=args.host, port=args.port, log_level="info")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
