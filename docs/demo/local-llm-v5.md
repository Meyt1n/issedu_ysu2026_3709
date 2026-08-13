# 本地大模型闭环（HCT-402 QLoRA v5）

自训 v5 适配器通过 **Ollama** 服务「本地证据助手」聊天，全链路本地推理。
参考机（RTX 4060 8GB）热启动单轮约 4–6 秒。
**v5 尚未完成正式评估，输出仅限教学演示，不构成任何医疗建议。**

模型权重、合并后的 GGUF 和 Ollama 模型名都在仓库外。别人要接近同一效果，必须在自己机器上准备模型，不要拷贝他人的 `C:\Users\...` 路径。

没有本地模型时：把 `OLLAMA_MODEL` 保持 `unavailable`，助手返回结构化降级，档案和规则仍可用。

## 架构

```
前端 AssistantView
   ↓ POST /api/v1/assistant/chat?household_id=..&member_id=..
后端 assistant_chat（HCT-403 安全链路）
   ├─ 事实注入：成员投影 + 活跃规则 + 最近事件
   ├─ 白名单工具调用（retrieve_knowledge 等）与引用校验
   ├─ 输出归一化 → 医疗边界检查 → 外链检查 → 降级兜底
   ↓ Ollama /api/chat（OLLAMA_BASE_URL，httpx trust_env=False 绕过系统代理）
本机 Ollama :11434 · 你登记的模型名
```

## 准备模型（仓库外）

Ollama 0.20.x 不能直接加载 GGUF LoRA（`loras are not yet implemented`）。
要把 QLoRA **合并进基座** 再转 GGUF，然后 `ollama create`：

1. 自行准备 Qwen3-4B 基座 + v5 adapter（Hugging Face 目录，放在仓库外，例如 `<本地模型根>\hct402-opt-v5\adapter`）。
2. 合并：`W' = W + (α/r)·BA`，得到 `<本地模型根>\hct402-v5-merged`。
3. 用 llama.cpp `convert_hf_to_gguf.py --outtype q8_0` 得到约 4.3GB 的 GGUF。
4. 编写 Modelfile：`FROM` 指向该 GGUF，使用 ChatML；若基座是 Qwen3，可在 assistant 起始注入空 `<think>` 块以跳过思考。
5. 在 **Modelfile 所在目录** 执行：

```powershell
ollama create hct402-qlora-v5 -f Modelfile
```

模型名可自定，下面环境变量与之保持一致即可。

## 启动

```powershell
ollama serve

$env:OLLAMA_BASE_URL = "http://127.0.0.1:11434"
$env:OLLAMA_MODEL = "<ollama list 里的模型名，例如 hct402-qlora-v5>"
$env:OLLAMA_TIMEOUT_SECONDS = "120"
```

若使用 `.env`，写入同样三项后重启 API。系统代理会把 localhost 打成 502 时，后端已对 Ollama 使用 `trust_env=False`。

只想先打通接口、没有 v5 权重时，可临时 `ollama pull` 一个本机已有的小模型，把 `OLLAMA_MODEL` 设成该名字。回答质量会与 v5 不同，医疗边界仍由后端拦截。

备选：`scripts/llm_sidecar.py` 用 transformers+peft 直载 safetensors 适配器（无需 GGUF，更慢）。在 **含 GPU 依赖的独立环境** 中运行：

```powershell
<你的 GPU Python>\python.exe scripts/llm_sidecar.py `
  --base "<仓库外>\base-model" `
  --adapter "<仓库外>\adapter" `
  --port 11435
```

然后把 API 的 `OLLAMA_BASE_URL` 指到 `http://127.0.0.1:11435`。

## 要接近「能根据家里药回答」的效果

1. 先走通 [视觉演示](vision-samples/README.md)，在自己的家庭成员上确认一条用药。
2. 打开助手页时选中 **同一个家庭和成员**。
3. 询问已确认事实范围内的照护问题（例如「现在在用哪些药」）。
4. 未选成员或事实为空时，模型应说「无法判断」；出现诊断/处方等词时后端降级。

不要复制他人的 `homecare-dev.sqlite3`。

## 已知限制

- v5 偶发输出训练契约全文、畸形 JSON 或超短回答；后端有解析与正则兜底。
- 安全拒答样本占比高，无上下文提问偏保守。
- 正式盲测未完成，过拟合风险存在。
- 部分 Ollama 桌面版会崩溃循环，可用 `ollama serve` 命令行启动。

## 可选：YOLO 与助手同一套演示

识别 worker 可挂载仓库外的 YOLO11n 药盒检测权重（登记 sha256 前缀以模型卡为准）：

```powershell
$env:HCT_VISION_WEIGHTS = "<仓库外的 YOLO 权重>\best.pt"
```

详见 [视觉演示说明](vision-samples/README.md)。
