# HCT YOLO11n 包装区域辅助模型

- 模型 ID：`hct-yolo11n-box-assist-experimental-v1.2-opt-a`
- 用途：检测药盒、药瓶、药板和条码等包装区域，供裁剪和证据定位使用。
- 约束：这是实验性辅助模型，不承担药品身份确认，不覆盖 OCR、条码或人工复核结果。
- 运行权重：`weights/best.pt`
- 来源：父目录 `data/hct201/runs/hct201_v1.2_opt_a_augplus_20260813/weights/best.pt`
- SHA-256：`b3611241787360ab517ff4169af974cd49ae46d63ccb3b3387481db1e07a8ecf`
- 默认设备：CPU；可通过 `HCT_VISION_DEVICE` 覆盖。

`best.pt` 已物理迁移到本目录，但被 `.gitignore` 排除，不进入 Git 提交。运行时由 `src/ai/vision/local_models.py` 默认发现本路径，也可用 `HCT_VISION_WEIGHTS` 指向其他经确认的权重。
