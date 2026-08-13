# 本地大模型闭环（HCT-402 QLoRA v5）

自训 v5 适配器通过 **Ollama** 服务「本地证据助手」聊天，全链路本地推理，
热启动单轮约 4~6 秒（RTX 4060 8GB）。
**v5 尚未完成正式评估，输出仅限教学演示，不构成任何医疗建议。**

## 架构

```
前端 AssistantView（打字机流式展示、模型标签）
   ↓ POST /api/v1/assistant/chat?household_id=..&member_id=..
后端 assistant_chat（HCT-403 安全链路）
   ├─ 事实注入：成员投影（用药/过敏/疾病/计划）+ 活跃规则告警 + 最近事件
   ├─ run_assistant：契约系统提示 → 调模型 → 输出归一化（response/answer 双契约、
   │   <think> 剥离、畸形 JSON 正则兜底）→ 医疗边界检查 → 外链检查 → 降级兜底
   ↓ Ollama /api/chat（OLLAMA_BASE_URL，httpx trust_env=False 绕过系统代理）
Ollama（11434）· 模型 hct402-qlora-v5:latest（Q8_0，4.3GB）
```

## 模型制作（已完成，产物在 local-models/gguf/）

Ollama 0.20.2 不支持 GGUF LoRA 适配器（"loras are not yet implemented"），
因此把 v5 **逐张量合并**进 base 后再转 GGUF：

1. `tmp/merge_lora.py`：W' = W + (α/r)·BA，流式合并 144 个目标层
   → `local-models\hct402-v5-merged`（HF bf16）
2. `llama.cpp-src/convert_hf_to_gguf.py --outtype q8_0`
   → `local-models\gguf\hct402-v5-merged-q8_0.gguf`（4.3GB）
3. `local-models\gguf\Modelfile`：FROM 合并版 GGUF + qwen2.5 系 ChatML 模板，
   模板在 assistant 起始注入**空 `<think>` 块**关闭 Qwen3 思考（匹配 v5
   训练配置，同时省掉 2/3 的生成 token）
4. `ollama create hct402-qlora-v5 -f Modelfile`

## 启动

```powershell
# 1. Ollama（托盘 app 0.20.2 崩溃循环，用 CLI 直接起；建议尽快升级 Ollama）
ollama serve

# 2. 后端环境变量
$env:OLLAMA_BASE_URL = "http://127.0.0.1:11434"
$env:OLLAMA_MODEL = "hct402-qlora-v5"
$env:OLLAMA_TIMEOUT_SECONDS = "120"
```

备选：`scripts/llm_sidecar.py` 是 transformers+peft 直载 safetensors 适配器的
Ollama 兼容服务（无需合并/转换，但 bitsandbytes 推理约 10 tok/s，单轮 60~80 秒），
Ollama 不可用时可回退。

## 已验证的闭环

扫描药盒 → 人工复核确认 → `medication_confirmed` 入档 →
事实投影更新 → 助手回答引用该药品（sources 带事件类型/规则编号）。

- 未选成员或事实为空时，v5 会如实说「无法判断」（先依据后解释的训练风格）；
- 触发医疗边界词（诊断/处方等）时后端降级为安全模板并提示联系医务人员；
- 热启动单轮约 4~6 秒；模型冷启动（Ollama 重新载入）首轮约 20~30 秒。

## 已知限制

- v5 偶发输出训练契约全文（`hct-llm-output/v1`）、畸形 JSON 或超短回答，
  后端有严格解析 + 契约映射 + 正则兜底三级归一化；
- 训练集中安全拒答样本占比高，无上下文提问偏保守（多为拒答）；
- `metrics.json` 的 eval_loss 异常低（1.8e-4），存在过拟合风险，正式评估未做；
- YOLO 定位为检测框（task=detect），非像素级语义分割；
- 本机 Ollama 托盘 app（0.20.2）存在崩溃循环，日志提示可升级 0.32.9；
  当前用 `ollama serve` 直跑规避。

## 配套：视觉链路的 v5 家族模型

识别 worker 同时挂载了同日训练的 YOLO11n 药盒检测权重
（`hct201_v1.2_opt_a_augplus_20260813`，已登记 sha256 前缀 b3611241）：

```powershell
$env:HCT_VISION_WEIGHTS = "C:\Users\32140\Desktop\实训--多模态医疗\data\hct201\runs\hct201_v1.2_opt_a_augplus_20260813\weights\best.pt"
```

识别详情中的陶土色「包装区域」框即 YOLO 通道；其裁剪会触发二次 OCR
补充证据（可能与全图 OCR 产生冲突，冲突一律进人工复核，这是设计行为）。
