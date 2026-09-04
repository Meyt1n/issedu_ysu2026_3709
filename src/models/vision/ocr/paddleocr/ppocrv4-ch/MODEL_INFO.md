# PaddleOCR PP-OCRv4 中文本地模型

- 引擎：PaddleOCR 2.7.3 兼容的 PP-OCRv4 中文模型
- 用途：整图文字检测与识别；YOLO 裁剪只作为补充证据。
- 语言：`ch`
- 本地目录：`src/models/vision/ocr/paddleocr/ppocrv4-ch/`
- 原始缓存来源：`C:/Users/32140/.paddleocr/whl/`

包含以下三组实际运行需要的模型：

- `det/ch/ch_PP-OCRv4_det_infer/`：中文文字检测
- `rec/ch/ch_PP-OCRv4_rec_infer/`：中文文字识别
- `cls/ch_ppocr_mobile_v2.0_cls_infer/`：文字方向分类

模型文件已物理迁移到本目录，但被 `.gitignore` 排除，不进入 Git 提交。`src/ai/vision/local_ocr.py` 和 `_paddle_worker.py` 默认从这里读取，并显式传给 PaddleOCR，避免首次运行从云端下载；可用 `HCT_OCR_MODEL_DIR` 覆盖。
