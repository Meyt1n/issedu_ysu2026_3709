# 本地视觉模型

视觉模型按用途分为两个运行目录：

- `yolo/hct-yolo11n-box-assist-experimental-v1.2-opt-a/`：药品包装区域辅助检测，只提供候选框，不直接确认药品身份。
- `ocr/paddleocr/ppocrv4-ch/`：PaddleOCR PP-OCRv4 中文检测、识别和方向分类模型，作为 OCR-first 链路的文字证据来源。

权重文件已经复制到本机 `src/models`，但因体积和安全边界被 `.gitignore` 排除。每个模型目录的 `MODEL_INFO.md` 记录来源、用途和校验信息；代码和这些说明文件随 Git 提交。
