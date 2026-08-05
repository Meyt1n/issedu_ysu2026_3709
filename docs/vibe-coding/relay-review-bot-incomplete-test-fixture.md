# Relay Review Bot 不完整交付测试夹具

本文件仅用于演练，不是产品功能，也不应合并到 `master`。

本演练任务要求新增 `GET /api/test/incomplete` 健康检查路由，并同时提供实现、自动测试、API 文档和回滚说明。本测试夹具故意只记录任务要求，不包含路由实现、测试或 OpenAPI 变更。

预期结果：任务元数据门禁和基础 CI 可以通过，但 Relay Review Bot 必须识别“验收条件未完成”，给出修改意见并使 `Relay Review Bot` 检查失败。
