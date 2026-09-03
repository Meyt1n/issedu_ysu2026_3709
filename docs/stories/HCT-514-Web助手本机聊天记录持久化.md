# HCT-514 Web 健康助手本机聊天记录持久化

- Issue：待开（本任务 agent 无 issues 权限，需维护者创建并回填）
- 关联：HCT-415（引用与会话体验）、HCT-451（助手全屏对话与多会话）、HCT-513（助手产品面撤回）
- FR/NFR：FR-08（本地证据助手可继续同一轮问答）；NFR-02（对话不上传、登出清除）；NFR-07（侧栏诚实说明保存范围）
- 风险等级：R2（浏览器本机存助手问答；不扩大授权、不新增 API、不写入服务端）
- 状态：实现完成，待 Issue/PR 与人工验收

## 1. Story

作为家庭照护者，我希望关掉浏览器再打开、只要还没退出登录，健康助手里的对话还在，这样就不用每次重问。

## 2. 产品决定

| 表面 | 决定 |
|---|---|
| Web 健康助手 | 对话、线索列表、当前线索和助手会话 ID 写入本机 `localStorage` |
| 隔离 | 仍按 `actorId / householdId / memberId`（及线索 ID）分键，不串家庭、不串成员 |
| 登出 | 仍调用 `clearChatSessionsForActor`，清除该身份在本机的助手对话 |
| 后端 | 不新增会话 API，不把对话上传服务端或日志 |
| 随身版 APP | 不改；`shared/voice/chatSession.ts` 仍是标签页 `sessionStorage` |
| 双端口 | 5173 成员前台与 5174 管理后台的 `localStorage` 按端口分区，两端历史分开 |

升级时若本机 `localStorage` 还没有同名键，把旧版 `sessionStorage` 里的助手键拷过去再删标签页副本，避免刷新丢掉当前标签里还在的对话。

## 3. 与冻结规格的冲突（不得默默忽略）

- HCT-415、HCT-451、[API 设计规范](../vibe-coding/06-API设计规范.md)、[AI 与 RAG 设计规范](../vibe-coding/07-AI与RAG设计规范.md) 仍写「只保存在当前标签页 `sessionStorage`」。
- 本增量按用户明确要求改为本机 `localStorage`（关浏览器再开可恢复；退出登录仍清除）。
- **不改**上述冻结正文。冲突记在此处，由维护者决定是否修订规格或恢复标签页临时存储。

## 4. 验收条件

1. Given 已登录并在健康助手发过消息；When 关闭浏览器再打开同一门户且仍保持登录；Then 同一身份/家庭/成员下能看到上次对话和线索列表。
2. Given 本机已有对话；When 退出登录再进入同一门户；Then 该身份的助手对话已清除。
3. Given 切换家庭或成员；When 打开助手；Then 不会看到另一个范围的对话。
4. Given 旧版还把对话留在 `sessionStorage`；When 升级后首次加载助手；Then 在 `localStorage` 尚空时迁入，且不覆盖已有本机记录。
5. Given 打开助手侧栏；When 阅读保存说明；Then 文案写明保存在这台电脑、不上传、退出登录后清除。

## 5. 实现与证据

- `src/web/src/assistant/chatSession.ts`：`storage()` 改为 `localStorage`；一次性从 `sessionStorage` 迁移同前缀键。
- `src/web/src/assistant/chatSession.test.ts`：范围隔离、登出清理、本机持久化、迁移且不覆盖。
- `src/web/src/views/AssistantView.vue`：侧栏说明改为本机保存。
- 登出路径仍走 `src/web/src/store.ts` 的 `clearChatSessionsForActor`。

## 6. 回滚

把 `chatSession.ts` 的 `storage()` 改回 `sessionStorage` 并恢复侧栏文案即可；无需数据迁移或后端回滚。已写入 `localStorage` 的旧对话键会残留在本机，登出或手动清站点数据可删掉。
