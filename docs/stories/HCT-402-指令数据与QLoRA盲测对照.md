# HCT-402：指令数据与 QLoRA 盲测对照

- 状态：进行中（本 PR 仅完成数据准备，不训练或发布模型）
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

## 明确不做

- 不在本增量执行 QLoRA、全参数微调、模型合并、量化或 Ollama 导入；
- 不提交真实家庭健康对话、真实患者数据、药盒图片、模型权重或训练缓存；
- 不把合成起步样本宣称为正式生产训练集；
- 不让模型生成风险等级、诊断、处方、停药、换药或剂量结论。

## 数据边界

LLM 训练样本的输入是已授权的 OCR token、条码结果、包装候选、主数据候选、规则结果和可见字段范围，不是原始图片，也不是完整数据库。字段来源必须可定位；证据不足或通道冲突时输出 `UNKNOWN`、`CONFLICT` 或 `REVIEW`。

## Given / When / Then

- Given 合成来源记录包含许可、去标识化、场景组和结构化 assistant 目标；When 运行准备脚本；Then 生成确定性的 train、validation 和 blind 目录，并输出无本机路径/密钥的 manifest。
- Given 两条记录属于同一 `scenario_group`；When 执行划分；Then 两条记录只能出现在同一个 split，盲测组不会进入训练或验证。
- Given blind 记录；When 生成训练输入；Then 输入不包含 assistant 标签，标签单独保存，只供评测阶段显式加载。
- Given 来源不是合成、未去标识化或训练许可不明；When 执行审计；Then 脚本失败，不生成可训练输出。

## 验收条件

- [ ] 数据卡记录来源、许可证、训练同意、去标识化、质量审查、删除传播和禁止用途
- [ ] 至少覆盖 `MATCHED`、`CONFLICT`、`UNKNOWN`、`REVIEW` 与 `REFUSE` 相关样本
- [ ] 训练/验证/盲测按场景组隔离，生成结果可由输入哈希和版本复现
- [ ] 盲测输入与标签分离，训练输出不包含盲测样本或 assistant 目标
- [ ] 审计拒绝重复 ID、重复场景跨 split、绝对路径、密钥模式、非合成来源和非法输出 Schema
- [ ] 本 PR 不改变运行时模型，不改变 Ollama 配置，不产生模型权重

## 验证命令

```powershell
uv run ruff check scripts/hct402_prepare_dataset.py tests/data/test_hct402_dataset.py
uv run pytest tests/data/test_hct402_dataset.py
python scripts/hct402_prepare_dataset.py --source tests/fixtures/hct402/starter_source.jsonl --output-dir tmp/hct402-prepared
git diff --check
```

## 回滚

删除本 PR 新增的数据规范、合成 fixture、准备脚本和测试；不需要回滚数据库、API、运行时模型或 Ollama。任何后续训练都必须重新引用通过评审的数据版本和 manifest 哈希。

## 当前限制

合成起步样本只用于验证数据协议和训练管线，不能证明基础模型或 QLoRA 模型效果。正式训练前仍需补充经许可的指令样本、独立盲测集、人工质量审查、模型卡和安全评估。
