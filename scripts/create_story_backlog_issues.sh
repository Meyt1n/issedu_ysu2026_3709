#!/usr/bin/env bash
# 批量创建 Story 补全 Issue（需具备 issues:write 权限的 gh 登录态）
# 用法：cd 仓库根目录 && bash scripts/create_story_backlog_issues.sh
# 输出：docs/planning/Issue创建结果-YYYY-MM-DD.md
set -euo pipefail

REPO="${GITHUB_REPOSITORY:-Meyt1n/issedu_ysu2026_3709}"
OUT="docs/planning/Issue创建结果-$(date -u +%Y-%m-%d).md"
mkdir -p docs/planning

if ! gh auth status >/dev/null 2>&1; then
  echo "请先 gh auth login（需 issues 写权限）" >&2
  exit 1
fi

probe=$(gh api "repos/${REPO}/issues" -X POST -f title='[probe] issue write test' -f body='delete me' 2>&1 || true)
if echo "$probe" | rg -q 'Resource not accessible'; then
  echo "当前 gh token 无 issues 写权限（403）。请用维护者 PAT 或本地 gh login 后重试。" >&2
  exit 1
fi
# 删除 probe issue（若创建成功）
probe_num=$(echo "$probe" | python3 -c "import sys,json; print(json.load(sys.stdin).get('number',''))" 2>/dev/null || true)
if [[ -n "$probe_num" && "$probe_num" != "" ]]; then
  gh issue close "$probe_num" -R "$REPO" --comment "权限探针，已关闭" >/dev/null 2>&1 || true
fi

create_issue() {
  local title="$1"
  local body="$2"
  local labels="${3:-}"
  echo "创建: $title"
  if [[ -n "$labels" ]]; then
    gh issue create -R "$REPO" --title "$title" --body "$body" --label "$labels"
  else
    gh issue create -R "$REPO" --title "$title" --body "$body"
  fi
}

{
  echo "# Issue 批量创建结果"
  echo ""
  echo "时间（UTC）：$(date -u +%Y-%m-%dT%H:%M:%SZ)"
  echo ""
  echo "| Story | Issue | 标题 |"
  echo "|---|---|---|"
} >"$OUT"

append_result() {
  local story="$1"
  local url="$2"
  local title="$3"
  echo "| $story | $url | $title |" >>"$OUT"
}

BODY_COMMON_FOOTER=$'

## 风险与回滚
- 风险等级：R1（默认）
- 合并前：维护者核对验收证据与回滚方式
- Story 文件：`docs/stories/`（若尚未建立，合并 PR 前补齐）
'

# 已有 Issue、跳过创建（Story 文件内已回填或 master 已建）
# HCT-460 → #501（聊天气泡，master）
# HCT-463 → #463（资讯运维诊断；Story 文件名仍 HCT-453）
# HCT-464 → #468（会话缓存；Story 文件名仍 HCT-455）
# HCT-454 → #465（缓存指纹隔离）

# --- §一 HCT-444～456（顺延 HCT-461/462；跳过已建）---
declare -a ISSUES=(
  "HCT-444|[HCT-444] 首页季节健康新闻与助手跳转|已在 master；默认无出口；待矩阵回填"
  "HCT-445|[HCT-445] 健康新闻白名单抓取与缓存降级|正式部署需 R3 出口复核"
  "HCT-447|[HCT-447] 侧栏助手导航唯一高亮|修复 HCT-444 双高亮"
  "HCT-448|[HCT-448] 症状用药空库友好降级|ADR-0007"
  "HCT-449|[HCT-449] 授权管理模板化与家庭友好闭环|纯前端"
  "HCT-450|[HCT-450] 助手回复智能度与编排优化|PR #453 已合并"
  "HCT-451|[HCT-451] 开放对话演示模式（ADR-0007 8C）|PR #467 #496"
  "HCT-461|[HCT-461] Web 截图驱动排版与助手全屏对话|顺延原 HCT-451 撞号；PR #456 待验收"
  "HCT-462|[HCT-462] 演示造数页错误分层与可用性修复|顺延原 HCT-452 撞号；PR #460"
  "HCT-453|[HCT-453] 前后台分端口登录入口|PR #462；ADR-0006"
  "HCT-455|[HCT-455] 成员前台登录差异化与总览排版修复|PR #472"
  "HCT-456|[HCT-456] 成员前台正确进入指引|PR #488"
)

# --- 子代理盘点：高优先级补票（无 Issue 的已实现切片）---
declare -a EXTRA_ISSUES=(
  "HCT-471|[HCT-471] 助手联网搜索开放模式安全验收|ADR-0007 / PR #496"
  "HCT-442|[HCT-442] 助手问题分类双通道|关联 #310；默认词表-only"
  "HCT-420|[HCT-420] 桌面端风险预算摘要卡片|Story 已有，待 PR/验收"
  "HCT-421|[HCT-421] 桌面端会话主动到期|Story 已有，待 PR/验收"
  "HCT-468|[HCT-468] 桌面端照护任务工作台|顺延 HCT-411 撞号"
  "HCT-469|[HCT-469] 家庭大屏脱敏数据展示|顺延 HCT-412 撞号"
  "HCT-470|[HCT-470] 家庭关系图谱服务端投影|顺延 HCT-419 撞号"
  "MOB-176|[MOB-176] 随身版语音助手真机验收矩阵|顺延 MOB-150 撞号；Related #210"
)

for entry in "${ISSUES[@]}" "${EXTRA_ISSUES[@]}"; do
  IFS='|' read -r story title note <<<"$entry"
  body="## Story 与需求
- Story：${story}
- 说明：${note}
- 清单：docs/planning/Story与Issue补全清单-2026-08-28.md
- 编号：docs/planning/编号顺延映射表-2026-08-28.md
${BODY_COMMON_FOOTER}"
  url=$(create_issue "$title" "$body")
  append_result "$story" "$url" "$title"
  sleep 1
done

# --- §十一 MOB-159～175（下一迭代全部纳入）---
declare -a MOB_ISSUES=(
  "MOB-159|[MOB-159] 手机首页季节健康资讯小卡片|对齐 HCT-444"
  "MOB-160|[MOB-160] 手机助手聊天气泡对齐网页版观感|对齐 HCT-452"
  "MOB-161|[MOB-161] 手机助手联网搜索开关与隐私说明|对齐 HCT-430/496"
  "MOB-162|[MOB-162] 手机知识库条目只读浏览|对齐 HCT-401"
  "MOB-163|[MOB-163] 手机环境行动卡真实天气联调验收|解除 MOB-157 Blocked"
  "MOB-164|[MOB-164] 手机「我的」页进入指引与联机三步清单|对齐 HCT-456"
  "MOB-165|[MOB-165] 手机健康资讯过期缓存提示与一键刷新|HCT-445/454 移动切片"
  "MOB-166|[MOB-166] 手机语音助手 15 秒停顿与自动朗读收口|PR #490"
  "MOB-167|[MOB-167] 手机助手多会话标签与历史栏|对齐 HCT-460"
  "MOB-168|[MOB-168] 手机助手流式回复「结束回复」与停止按钮|对齐 HCT-474"
  "MOB-169|[MOB-169] 手机刷脸登录引导（若后续支持）|可选"
  "MOB-170|[MOB-170] 手机演示包与健康新闻/助手连续演示脚本|HCT-405 移动切片"
  "MOB-171|[MOB-171] 手机弱网下列表骨架屏与超时重试文案|MOB-112/113 增强"
  "MOB-172|[MOB-172] 手机通知栏计划提醒真机矩阵签收|MOB-153 设备验收"
  "MOB-173|[MOB-173] 手机风险告警 HCT-458 字段真机截图|依赖 PR #481"
  "MOB-174|[MOB-174] 手机横屏与折叠屏基础布局不走样|NFR-07"
  "MOB-175|[MOB-175] 手机助手引用依据折叠展开|对齐 HCT-415"
)

for entry in "${MOB_ISSUES[@]}"; do
  IFS='|' read -r story title note <<<"$entry"
  body="## Story 与需求
- Story：${story}（下一迭代；需新建 docs/stories/${story}-*.md）
- 说明：${note}
- 清单：docs/planning/Story与Issue补全清单-2026-08-28.md §十一
${BODY_COMMON_FOOTER}"
  url=$(create_issue "$title" "$body")
  append_result "$story" "$url" "$title"
  sleep 1
done

# --- §十二 HCT-5xx / NEXT ---
declare -a NEXT_ISSUES=(
  "HCT-501|[HCT-501] 需求追踪矩阵与 Story 状态回填|治理 W0"
  "HCT-502|[HCT-502] 收口 HCT-458：合并 PR #481 并联动 MOB-156|治理 W0"
  "HCT-503|[HCT-503] 三档部署 MySQL 备份恢复实跑与 R3|证据 W1"
  "HCT-504|[HCT-504] QLoRA 真实训练与盲测对照模型卡|证据 W1"
  "HCT-505|[HCT-505] 演示机人脸阈值标定与教学级验收|证据 W1"
  "HCT-506|[HCT-506] 真实链路连续演示与最终验收门禁|证据 W1"
  "HCT-507|[HCT-507] ADR-0007 出网隐私 R3 与 badcase 回归池|成熟度 W2"
  "HCT-508|[HCT-508] 助手统一安全策略真实 Ollama 联调冒烟|成熟度 W2"
  "NEXT-M1|[NEXT-M1] MOB-148 发布 Gate 阻塞项集中收口|移动 W3"
  "NEXT-M2|[NEXT-M2] 语音真机验收与隐私 R3（HCT-412/MOB-150）|移动 W3"
)

for entry in "${NEXT_ISSUES[@]}"; do
  IFS='|' read -r story title note <<<"$entry"
  body="## Story 与需求
- Story：${story}
- 波次：${note}
- 详情：docs/planning/Story卡片集-HCT-5xx与NEXT.md
${BODY_COMMON_FOOTER}"
  url=$(create_issue "$title" "$body")
  append_result "$story" "$url" "$title"
  sleep 1
done

echo "" >>"$OUT"
echo "完成。共创建 $(( ${#ISSUES[@]} + ${#EXTRA_ISSUES[@]} + ${#MOB_ISSUES[@]} + ${#NEXT_ISSUES[@]} )) 个 Issue。" >>"$OUT"
echo "已跳过：HCT-460(#501)、资讯运维(#463)、会话缓存(#468)、HCT-454(#465)。" >>"$OUT"
echo "结果已写入 $OUT"
