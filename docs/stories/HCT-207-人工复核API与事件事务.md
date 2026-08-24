# HCT-207：人工复核 API/UI、幂等确认和事件事务

- 需求：FR-03
- 状态：进行中
- 负责人：Shen-huang-123
- 复核人：待项目组指定
- 风险：R3
- 依赖：HCT-103、HCT-104
- 允许修改：`src/api/app/routes.py`、`src/api/app/schemas.py`、`src/api/app/models.py`、`migrations/versions/`、`tests/`

## 用户价值

视觉识别结果经人工复核后确认为事实——接受、修正或拒识，每次操作幂等可审计。

## 范围

- 复核 API：ACCEPT / CORRECT / REJECT 三种操作
- 幂等键绑定（复用 HCT-103 基础设施）
- 复核确认后事务写入 HealthEvent + OutboxMessage
- 与 HCT-104 文件上传对接

本次增量还补充了药品识别结果卡：确认前集中展示名称、规格、厂家、用途、注意事项、禁忌人群和置信度；“确认保存”是唯一进入健康档案的入口，候选展示本身不产生健康事件。

## Given / When / Then

- Given 视觉任务结果；When 人工提交 ACCEPT；Then 创建 CONFIRMED HealthEvent。
- Given 同一复核幂等键重复提交；When 幂等命中；Then 返回已有结果。
- Given 复核操作为 CORRECT；When 提交修正数据；Then 创建补偿事件关联原视觉结果。

## 测试

- ACCEPT/CORRECT/REJECT 三种操作
- 幂等去重
- 未授权文件拒绝
- 事务回滚验证
