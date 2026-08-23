# HCT-P0 核心能力验收包

更新时间：2026-08-22

这份验收包把目前仍未关闭的核心能力统一成一套可复跑的门禁。它的原则是：

- 仓库里的合成夹具只能验证代码和报告格式，不能证明正式药品准确率、模型质量或真实服务商联调；
- 任何缺少批准、固定集、哈希、人工复核或回滚证据的门禁都输出 `BLOCK_*`；
- 模型权重、真实药品图片、真实健康数据、原始 OCR/对话内容和运行日志放在仓库外，只在报告中保存哈希和证据编号；
- 通过机器门禁也不等于发布，R3 复核和项目负责人签署仍然是人工步骤。

## 1. 验收范围和入口

| 能力 | 机器入口 | 正式通过条件 | 当前基线 |
| --- | --- | --- | --- |
| HCT-201 固定药品集 | `scripts/hct201_fixed_set_gate.py` | 12～20 个批准药品、固定 known 集、unknown 集、conflict 集、授权/分组/删除证据齐全 | 阻塞，仓库没有可发布真实固定集 |
| HCT-205 OCR/条码/主数据 | `scripts/hct205_accuracy_report.py` | 冻结结果 JSONL、真实批准范围、字段/条码/状态准确率达到阈值、失败原因和阈值版本齐全 | 阻塞，只有契约和合成链路 |
| HCT-203 YOLO/QLoRA | `scripts/hct203_release_gate.py` | 独立评估、hard-negative、模型/报告哈希、盲测或真实 test、回滚演练齐全 | 阻塞，当前仍是实验/候选状态 |
| HCT-302 规则 | `scripts/hct302_acceptance_report.py` | 重复成分、过敏、有限相互作用和严重案例均有批准案例、来源、规则版本、主数据版本 | 代码已有，正式案例包未关闭 |
| HCT-308 提醒 | `scripts/hct308_acceptance_report.py` | 确认、延期、漏服、疗程结束、逾期升级、照护者升级六条本地 API 证据完整 | 单元测试已有，连续 API/通知证据待跑 |
| HCT-403 助手 | `scripts/hct403_assistant_acceptance_gate.py` | QLoRA 真实盲测、红队、无证据拒答、Ollama 断连降级全部通过 | 本地工具链已有，正式盲测和完整安全证据未完成 |
| HCT-305 天气 | `scripts/hct305_provider_preflight.py` | HTTPS 域名白名单、行政区划白名单、真实提供方一次联调、响应归一化通过 | UAPIS 适配已写，部署白名单和真实联调待配置 |
| HCT-405 连续主线 | `scripts/hct405_acceptance_gate.py` | 登录→成员上下文→扫描→人工确认→健康事件→规则提醒→助手解释→离线重启链路通过 | 合成 E2E 较全，发布模型/离线演练/R3 未完成 |
| HCT-409 发布 | `scripts/hct409_release_gate.py` | API P95、视觉全链路 P95、隐私/安全/红队/依赖审计、人工读屏、R3 和负责人签署齐全 | 自动化基础已有，剩余发布证据未完成 |

## 2. 执行顺序

### 2.1 数据和视觉

先由数据负责人在仓库外冻结 `HCT-201` manifest。每一行必须有 `sample_id`、`drug_id` 或 unknown/conflict 分类、来源许可、真实实体/会话分组、删除引用、固定集标记、授权评审引用。然后运行：

```powershell
uv run python scripts/hct201_formal_gate.py `
  --manifest <外部目录>\hct201-manifest.jsonl `
  --report <外部目录>\hct201-formal.json

uv run python scripts/hct201_fixed_set_gate.py `
  --manifest <外部目录>\hct201-manifest.jsonl `
  --report <外部目录>\hct201-fixed-set.json
```

固定集门禁通过后，使用同一批次的 OCR、条码和本地主数据结果生成 JSONL。推荐字段如下：

```json
{
  "sample_id": "real-sample-001",
  "dataset_status": "APPROVED",
  "dataset_scope": "approved_real_fixed_set",
  "channel": "ocr",
  "expected_status": "MATCHED",
  "predicted_status": "MATCHED",
  "confidence": 0.97,
  "threshold_version": "ocr-barcode-fusion-v1",
  "source_ref": "review/2026-08-22/sample-001",
  "expected": {"drug_name": "…", "specification": "…"},
  "predicted": {"drug_name": "…", "specification": "…"}
}
```

报告命令：

```powershell
uv run python scripts/hct205_accuracy_report.py `
  --results <外部目录>\hct205-results.jsonl `
  --threshold-version ocr-barcode-fusion-v1 `
  --report <外部目录>\hct205-accuracy.json
```

当前默认阈值是字段准确率 95%、条码准确率 98%、状态准确率 95%。正式项目可以在独立评审中调整，但必须把调整理由、版本和回滚阈值写入报告。

### 2.2 模型发布前

YOLO 先跑真实批准固定集上的独立 test、CPU/GPU P95 和 hard-negative 复核；QLoRA 使用 `scripts/hct402_predict_blind.py` 和 `scripts/hct402_evaluate_blind.py` 生成真实盲测报告。两者都必须准备回滚报告：旧版本、恢复动作、恢复后的版本绑定和验证结果。

```powershell
uv run python scripts/hct203_release_gate.py `
  --model-kind yolo `
  --registry <外部目录>\yolo-registry.json `
  --dataset-gate <外部目录>\hct201-fixed-set.json `
  --evaluation <外部目录>\yolo-independent-evaluation.json `
  --rollback <外部目录>\yolo-rollback.json `
  --report <外部目录>\hct203-yolo.json

uv run python scripts/hct203_release_gate.py `
  --model-kind qlora `
  --registry <外部目录>\qlora-registry.json `
  --dataset-gate <外部目录>\hct201-fixed-set.json `
  --evaluation <外部目录>\hct402-blind-evaluation.json `
  --rollback <外部目录>\qlora-rollback.json `
  --report <外部目录>\hct203-qlora.json
```

命令只会给出 `READY_FOR_R3_REVIEW`，不会自行把模型改成生产发布状态。当前已有 registry 的 `EXPERIMENTAL_UNRELEASED` 语义必须继续保留，直到独立复核完成。

### 2.3 规则和提醒

规则案例放在仓库外，不能写真实姓名、病历或原始健康正文。每条严重案例至少要带：规则版本、批准主数据版本、来源事件引用、预期严重等级、预期事件 ID。运行：

```powershell
uv run python scripts/hct302_acceptance_report.py `
  --cases <外部目录>\hct302-approved-cases.jsonl `
  --report <外部目录>\hct302-rules.json
```

提醒链路由 API/E2E runner 产生事件类型和证据引用，必须覆盖：`confirm`、`defer`、`missed`、`course_end`、`escalation`、`caregiver_escalation`。

```powershell
uv run python scripts/hct308_acceptance_report.py `
  --trace <外部目录>\hct308-trace.json `
  --report <外部目录>\hct308-reminders.json
```

### 2.4 助手和天气

助手报告必须绑定真实本地模型 SHA-256。红队报告至少覆盖医疗拒答、提示注入、跨成员越权、无证据场景；断连报告必须证明 Ollama 不可用时返回结构化降级，而不是编造答案。

```powershell
uv run python scripts/hct403_assistant_acceptance_gate.py `
  --blind <外部目录>\hct402-blind-evaluation.json `
  --red-team <外部目录>\hct403-red-team.json `
  --degradation <外部目录>\hct403-ollama-offline.json `
  --report <外部目录>\hct403-assistant.json
```

天气先做离线预检，部署机明确填入获批域名；配置正确后再加 `--live`，只发送城市/区县编码：

```powershell
uv run python scripts/hct305_provider_preflight.py `
  --provider uapis `
  --url https://<获批天气域名>/<路径> `
  --allowed-host <获批天气域名> `
  --city-code 130600 `
  --district-code 130629 `
  --live `
  --report <外部目录>\hct305-weather.json
```

## 3. 连续主线和发布汇总

HCT-405 的 trace 必须把下面的单条主线一次跑完，而不是临时手工写数据库：

`密码首次进入 → 创建家庭 → 绑定成员 → 动态人脸 → 自动进入成员 → 扫描药品 → 人工确认 → 健康事件 → 重复/相互作用提醒 → 助手展示依据`

完成后运行：

```powershell
uv run python scripts/hct405_acceptance_gate.py `
  --trace <外部目录>\hct405-core-trace.json `
  --report <外部目录>\hct405-core-e2e.json

uv run python scripts/hct409_release_gate.py `
  --evidence <外部目录>\hct409-release-evidence.json `
  --report <外部目录>\hct409-release.json

uv run python scripts/hct_p0_acceptance.py `
  --evidence-dir <外部目录> `
  --report <外部目录>\hct-p0-summary.json
```

总汇总器缺少任何一个报告都会 `BLOCK_P0_ACCEPTANCE`。这正是当前状态：代码、单元测试和合成演示可以继续使用，但在真实固定集、正式模型、真实天气和 R3 签署补齐前，不能把 HCT-201、HCT-203、HCT-205、HCT-206、HCT-405、HCT-409 标成已验收。

## 4. 回滚和责任

- 数据：把数据版本标记为不可用，恢复上一批准 manifest，隔离/删除可控派生制品；不覆盖旧报告。
- 模型：恢复上一版本绑定，撤销当前版本，保留旧版本哈希和回滚原因；家庭运行时回到 `vision_model_version=unavailable` 或上一批准版本。
- 规则：切回上一 `ruleset_version` 和批准主数据版本，保留已生成事件的审计引用。
- 天气：关闭 `WEATHER_ADAPTER`，保持本地健康事件、规则和提醒可用。
- 助手：Ollama/知识不可用时回到结构化降级和专业咨询提示，不输出药物决定。

所有正式通过结果应作为外部制品保存，并在需求追踪矩阵中登记哈希、PR、人工复核人和回滚入口。
