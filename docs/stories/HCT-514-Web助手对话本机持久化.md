# HCT-514 Web 健康助手对话本机持久化

- Issue：待开（本任务 agent 无 issues 权限，需维护者创建并回填）
- 关联：HCT-415（助手会话体验）、HCT-451（助手多会话栏）、HCT-447（侧栏图标不重复）
- FR/NFR：FR-08（本地证据助手可继续上一轮问答）；NFR-02（对话仍不上传、不写服务端会话）；NFR-07（侧栏诚实说明本机保存与登出清除）
- 风险等级：R2（浏览器本机存助手问答，不扩大授权、不新增 API；共用电脑时登出仍清除）
- 状态：实现完成，待 Issue/PR 与人工验收

## 1. Story

作为家庭照护者，我希望关掉浏览器后再打开健康助手时，上次的对话还在。对话只存在这台电脑上，退出登录后清除。

## 2. 产品决定

| 表面 | 本增量 | 不改 |
|---|---|---|
| Web 健康助手 | `chatSession.ts` 从 `sessionStorage` 改为 `localStorage`；关标签/关浏览器后，保持登录即可恢复 | 不新增后端会话 API、不上云、不跨设备同步 |
| 升级迁移 | 若 local 无同名键，从 `sessionStorage` 拷贝后删除旧键，避免刷新丢掉当前标签里的旧对话 | 已有 local 数据不被 session 覆盖 |
| 登出 | 继续 `clearChatSessionsForActor` | 登录会话本身仍按现有 localStorage 规则 |
| 隔离与限长 | 仍按 actor / household / member 隔离；最多 24 条、12 条线索 | 成员前台 5173 与管理后台 5174 因端口分区，历史分开 |
| 侧栏图标 | 「人脸凭证 / 登录设置」改为锁，避免与授权钥匙、用药盾牌重复 | 不改页面功能 |
| 随身版 APP | 不改 | `APP` / `shared/voice/chatSession.ts` 仍为标签页会话 |

## 3. 与冻结规格的冲突（不得默默忽略）

- HCT-415、HCT-451 与 [API 设计规范](../vibe-coding/06-API设计规范.md)、[AI 与 RAG 设计规范](../vibe-coding/07-AI与RAG设计规范.md) 仍写「只保存在当前标签页 `sessionStorage`」。
- 本增量**不改**上述冻结正文。产品面按用户明确要求改为本机 `localStorage`；冲突记在此处，由维护者决定是否修订规格。

## 4. 验收条件

1. Given 已登录并在健康助手发过消息；When 关闭标签或浏览器后用同一账号再打开助手；Then 能看到上次对话与线索列表。
2. Given 本机已有旧版 `sessionStorage` 对话、local 无同名键；When 打开助手；Then 对话迁到 local，且不被空 local 丢掉。
3. Given local 已有对话、session 里是另一份；When 打开助手；Then 保留 local，删除 session 副本。
4. Given 退出登录；When 再登录同一账号前；Then 该 actor 的本机对话已清除。
5. Given 侧栏说明；When 阅读；Then 文案为「对话保存在这台电脑上，不上传；退出登录后清除。」
6. Given 管理后台侧栏；When 对比「授权管理」与「人脸凭证」；Then 后者为锁图标，不与钥匙或用药盾牌重复。

## 5. 实现与证据

- `src/web/src/assistant/chatSession.ts`：读写改为 `localStorage`；一次性从 `sessionStorage` 迁移；本机存储被拦截时回退当前标签页。
- `src/web/src/assistant/chatSession.test.ts`：隔离、登出清理、迁移且不覆盖已有 local。
- `src/web/src/views/AssistantView.vue`：侧栏一句说明。
- `src/web/src/ui/navigation.ts`：人脸凭证侧栏改为锁图标。

## 6. 回滚

把 `storage()` 改回 `sessionStorage` 并恢复侧栏文案即可；无服务端迁移。
