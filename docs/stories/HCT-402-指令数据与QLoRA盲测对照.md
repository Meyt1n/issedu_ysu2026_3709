# HCT-402：指令数据与 QLoRA 盲测对照

- 状态：进行中（已生成外部 `APPROVED_FOR_TRAINING` 路由/安全数据目录并完成 dry-run；尚未执行真实训练、盲测对照或发布模型）
- 需求：FR-08、NFR-05、NFR-06
- 风险：R3；模型输出涉及证据、权限和医疗安全边界
- 主责角色：项目负责人（CV/LLM）
- 负责人：Meyt1n
- 复核人：Shen-huang-123
- 前置依赖：HCT-401、HCT-403（均已合并）
- 关联 Issue：[#65](https://github.com/Meyt1n/issedu_ysu2026_3709/issues/65)

## 用户价值

先建立可审计、可分组、可复现的本地指令数据，后续才能公平比较基础模型和 QLoRA 模型。数据只教模型执行工具、引用证据、结构化输出、澄清和安全拒答，不让模型记忆家庭事实或替代规则引擎。

## 本次范围

- 建立 HCT-402 指令数据卡和字段规范；
- 提供仅含虚构内容的合成起步样本，覆盖匹配、冲突、未知、字段授权和危险医疗请求拒答；
- 按 `scenario_group` 固定划分训练、验证和盲测，防止同一场景跨集合泄漏；
- 生成 LLaMA Factory 可消费的训练/验证 JSONL，以及与训练输入分离的盲测输入和标签；
- 增加许可证、去标识化、路径/密钥、重复 ID 和盲测隔离审计。
- 增加离线盲测评估器：校验预测集合完整性、结构化格式、状态/路由、引用来源、安全拒答和未授权字段泄露；
- 用合成回放生成可复现的演示报告，报告明确标记为 `synthetic_fixture_only`。
- 增加 `hct402_train_qlora.py`：锁定 seed、QLoRA/4-bit NF4、LoRA 模块、assistant-only loss、数据 manifest 和外部产物元数据；
- 增加 `hct402_predict_blind.py`：只读取 blind inputs 生成真实模型结构化预测，不加载标签，再交给既有评估器。
- 增加 `hct402_prepare_approved_dataset.py`：从仓库外的公开来源候选生成受范围批准的路由/安全训练目录，移除未经事实核验的参考答案，并写入审批、训练同意、脱敏、人工范围审查、删除策略和 train/validation/blind 哈希记录。

## 明确不做

- 不在仓库内执行 QLoRA、全参数微调、模型合并、量化或 Ollama 导入；实际运行必须在受控外部训练目录完成；
- 不提交真实家庭健康对话、真实患者数据、药盒图片、模型权重或训练缓存；
- 不把合成起步样本宣称为正式生产训练集；
- 不让模型生成风险等级、诊断、处方、停药、换药或剂量结论。

## 数据边界

LLM 训练样本的输入是已授权的 OCR token、条码结果、包装候选、主数据候选、规则结果、可见字段范围或经批准的外部参考边界文本，不是原始图片、完整数据库或未经裁剪的医学答案。字段来源必须可定位；证据不足或通道冲突时输出 `UNKNOWN`、`CONFLICT` 或 `REVIEW`。

## Given / When / Then

- Given 合成来源记录包含许可、去标识化、场景组和结构化 assistant 目标；When 运行准备脚本；Then 生成确定性的 train、validation 和 blind 目录，并输出无本机路径/密钥的 manifest。
- Given 两条记录属于同一 `scenario_group`；When 执行划分；Then 两条记录只能出现在同一个 split，盲测组不会进入训练或验证。
- Given blind 记录；When 生成训练输入；Then 输入不包含 assistant 标签，标签单独保存，只供评测阶段显式加载。
- Given 来源不是合成、未去标识化或训练许可不明；When 执行审计；Then 脚本失败，不生成可训练输出。
- Given 外部来源已通过公开许可证核验且项目负责人批准内部路由/安全范围；When 运行 `hct402_prepare_approved_dataset.py`；Then 生成 `APPROVED_FOR_TRAINING` manifest、审批/删除记录和无参考答案的 train/validation/blind 目录。
- Given approved manifest 的审批、脱敏、人工审查、删除策略或 split 哈希缺失/不一致；When 运行 QLoRA 入口；Then 训练在加载阶段失败并报告具体门禁原因。
- Given 盲测输入、标签和结构化预测文件；When 执行评估器；Then 预测 ID 必须与标签一一对应，并输出带输入/标签/预测哈希的指标报告。
- Given 预测引用未出现在输入证据或泄露被授权字段；When 执行评估器；Then 对应引用/安全指标失败，不能被平均分掩盖。

## 验收条件

- [x] V1.1 数据卡和外部审批记录记录来源、许可证、训练同意、去标识化、人工范围审查、删除传播和禁止用途
- [ ] 至少覆盖 `MATCHED`、`CONFLICT`、`UNKNOWN`、`REVIEW` 与 `REFUSE` 相关样本
- [x] 训练/验证/盲测按场景组隔离，生成结果可由输入哈希和版本复现
- [x] QLoRA dry-run 校验 approved manifest、有效 batch、LoRA 配置和 assistant-only loss 边界；真实运行拒绝未批准的合成/未发布数据
- [x] 真实 blind 预测入口不加载 labels，并输出可交给评估器的结构化 JSONL
- [x] 盲测输入与标签分离，训练输出不包含盲测样本或 assistant 目标
- [x] 审计拒绝重复 ID、重复场景跨 split、绝对路径、密钥模式、非合成来源和非法输出 Schema
- [x] 评估器拒绝预测缺失/重复/多余 ID，并输出格式、状态、路由、引用和安全指标
- [x] 合成回放报告标记为 `synthetic_fixture_only`，不被解释为模型效果
- [x] 本 PR 不改变运行时模型，不改变 Ollama 配置，不在仓库产生模型权重

## 验证命令

```powershell
uv run ruff check scripts/hct402_prepare_dataset.py scripts/hct402_prepare_approved_dataset.py scripts/hct402_train_qlora.py scripts/hct402_evaluate_blind.py tests/data/test_hct402_dataset.py tests/data/test_hct402_approved_dataset.py tests/data/test_hct402_blind_eval.py
uv run pytest tests/data/test_hct402_dataset.py tests/data/test_hct402_blind_eval.py
uv run pytest tests/data/test_hct402_training.py tests/data/test_hct402_approved_dataset.py tests/unit/test_hct402_predict_blind.py
uv run python scripts/hct402_train_qlora.py --prepared-dir <外部 approved prepared> --output-dir <全新外部目录> --base-model Qwen/Qwen3-4B --dry-run
uv run python scripts/hct402_predict_blind.py --inputs <外部 blind inputs> --output <外部 predictions.jsonl> --base-model Qwen/Qwen3-4B --model-version <版本> --dry-run
uv run python scripts/hct402_prepare_dataset.py --source tests/fixtures/hct402/starter_source.jsonl --output-dir tmp/hct402-blind-eval-demo/prepared
uv run python scripts/hct402_evaluate_blind.py --inputs tmp/hct402-blind-eval-demo/prepared/blind/inputs.jsonl --labels tmp/hct402-blind-eval-demo/prepared/blind/labels.jsonl --predictions tests/fixtures/hct402/synthetic-evaluator-replay.jsonl --model-name synthetic-evaluator-replay --model-version fixture-v1 --output tmp/hct402-blind-eval-demo/report.json
git diff --check
```

## 回滚

删除本 PR 新增的数据规范、合成 fixture、准备/训练/预测脚本和测试；不需要回滚数据库、API、运行时模型或 Ollama。任何后续训练都必须重新引用通过评审的数据版本和 manifest 哈希。

## 当前限制

合成起步样本和回放报告只用于验证数据协议、评估器和演示链，不能证明基础模型或 QLoRA 模型效果。当前已生成
`hct402-instruction-approved-v1` 的 `APPROVED_FOR_TRAINING` manifest，但它只批准内部路由/安全实验；仍需补充真实模型预测、模型卡、安全评估、回滚演练和 R3 发布复核，不能据此发布模型或形成医学事实结论。
