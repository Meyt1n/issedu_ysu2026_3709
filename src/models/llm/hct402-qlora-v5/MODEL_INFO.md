# hct402-qlora-v5

## 默认模型

- Ollama 模型名：`hct402-qlora-v5`
- 权重文件：`hct402-v5-merged-q8_0.gguf`
- 量化：GGUF Q8_0
- 文件大小：4,280,404,832 bytes
- SHA-256：`8E6E7E54CA6475DE218A864B9091EA4998B9D19350743A98D0A90DE2E78F1716`
- 注册文件：同目录下的 `Modelfile`

## 注册

```powershell
.\scripts\register_local_llm_model.ps1
```

或在仓库根目录执行：

```powershell
ollama create hct402-qlora-v5 -f src/models/llm/hct402-qlora-v5/Modelfile
```

该权重文件只作为本地教学演示运行资产保存，已被 Git 忽略，不代表医疗产品发布或临床验证结论。
