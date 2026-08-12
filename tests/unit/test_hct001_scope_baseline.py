import re
from pathlib import Path
from urllib.parse import unquote

ROOT = Path(__file__).resolve().parents[2]
REQUIREMENTS = ROOT / "docs/vibe-coding/01-需求规格说明书.md"
PAGE_DESIGN = ROOT / "docs/vibe-coding/18-产品信息架构与页面设计.md"
STORY = ROOT / "docs/stories/HCT-001-产品范围医疗边界与十页原型.md"
REVIEW = ROOT / "docs/reviews/HCT-001-P0范围与十页原型评审记录.md"

MANDATORY_DOCS = (
    ROOT / "AGENTS.md",
    ROOT / "README.md",
    ROOT / "docs/vibe-coding/开发前必读与Vibe Coding工作流.md",
    ROOT / "docs/vibe-coding/00-文档导航.md",
    ROOT / "docs/vibe-coding/19-项目全生命周期开发流程.md",
    ROOT / "docs/vibe-coding/PR任务关联与Relay Review Bot 工作流.md",
    ROOT / "docs/vibe-coding/PR Review Bot 操作规范.md",
)

CHANGED_DOCUMENTS = (
    REQUIREMENTS,
    PAGE_DESIGN,
    STORY,
    REVIEW,
    ROOT / "docs/vibe-coding/12-需求追踪矩阵.md",
)

CORE_PAGES = (
    "家庭总览",
    "成员健康档案",
    "视觉扫描中心",
    "人工复核中心",
    "家庭健康图谱",
    "用药安全中心",
    "健康计划中心",
    "本地健康助手",
    "家庭健康大屏",
    "模型实验室",
)

HARD_COMMITMENTS = (
    "家庭版健康数据默认不出网",
    "冲突/未知/低质量不得自动进入健康状态",
    "撤权立即生效",
    "严重提醒不被预算压制",
    "不做诊断、处方、停药、换药或剂量判断",
    "不提供买药、问诊、广告、佣金或健康消费导流",
)

PAGE_COMMITMENTS = (
    "家庭健康数据默认不出网",
    "需人工确认",
    "可见范围、用途、到期时间",
    "INFO/GENERAL",
    "基于哪些事实/规则/文档",
    "无导流",
)

SAFE_STATE_PHRASES = {
    "家庭总览": ("不回显其他家庭缓存", "不进入风险摘要"),
    "成员健康档案": ("不预填敏感旧值", "不泄露字段存在性"),
    "视觉扫描中心": ("结构化失败原因", "禁止确认入库"),
    "人工复核中心": ("不产生部分健康事件", "不默认最高分候选"),
    "家庭健康图谱": ("隐藏未授权节点", "不为未确认事实建节点/边"),
    "用药安全中心": ("不显示假等级", "不给肯定用药判断"),
    "健康计划中心": ("不保存部分变更", "禁止优化或切换计划"),
    "本地健康助手": ("检索前拒绝越权", "不输出医疗结论"),
    "家庭健康大屏": ("不闪现成员敏感信息", "未确认数据不进入"),
    "模型实验室": ("禁止云端回退", "禁止发布"),
}


def read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def test_p0_scope_names_exactly_ten_core_pages() -> None:
    requirements = read(REQUIREMENTS)
    page_design = read(PAGE_DESIGN)

    requirement_pages = tuple(
        match.strip()
        for match in re.findall(r"^\| P0-\d{2} \| ([^|]+) \|", requirements, re.MULTILINE)
    )
    design_headings = tuple(
        match.strip()
        for match in re.findall(r"^### 3\.\d+ ([^\n]+)$", page_design, re.MULTILINE)
    )
    design_pages = tuple(
        heading for heading in design_headings if not heading.startswith("授权设置")
    )

    assert requirement_pages == CORE_PAGES
    assert design_pages == CORE_PAGES
    assert len(set(requirement_pages)) == len(CORE_PAGES)
    assert len(set(design_pages)) == len(CORE_PAGES)
    assert sum(heading.startswith("授权设置") for heading in design_headings) == 1
    assert "### 3.5 家庭健康图谱" in page_design


def test_each_core_page_defines_all_required_states() -> None:
    page_design = read(PAGE_DESIGN)
    expected_header = "| 页面 | 正常 | 加载 | 空 | 错误 | 离线 | 未授权 | 低置信 |"

    assert "## 4.4 十页状态矩阵" in page_design
    assert expected_header in page_design
    state_rows = tuple(
        line
        for line in page_design.splitlines()
        if any(line.startswith(f"| {page} |") for page in CORE_PAGES)
    )
    state_pages = tuple(row.split("|", maxsplit=2)[1].strip() for row in state_rows)
    assert state_pages == CORE_PAGES
    for page, row in zip(state_pages, state_rows, strict=True):
        assert row.count("|") == 9
        assert all(cell.strip() for cell in row.strip("|").split("|"))
        assert all(phrase in row for phrase in SAFE_STATE_PHRASES[page])


def test_product_hard_commitments_remain_explicit() -> None:
    requirements = read(REQUIREMENTS)
    page_design = read(PAGE_DESIGN)

    for commitment in HARD_COMMITMENTS:
        assert commitment in requirements
    for commitment in PAGE_COMMITMENTS:
        assert commitment in page_design


def test_story_and_review_evidence_are_complete() -> None:
    story = read(STORY)
    review = read(REVIEW)

    for field in (
        "用户价值",
        "范围与非目标",
        "允许修改",
        "Given / When / Then",
        "负责人",
        "复核人",
        "验证命令",
        "回滚",
    ):
        assert field in story

    for field in ("接受项", "延期项", "责任人", "评审结论", "回滚"):
        assert field in review


def test_mandatory_docs_and_local_links_resolve() -> None:
    for path in MANDATORY_DOCS:
        assert path.is_file()
        assert path.stat().st_size > 0

    for document in CHANGED_DOCUMENTS:
        for raw_target in re.findall(r"\[[^]]+]\(([^)]+)\)", read(document)):
            target = raw_target.strip("<>").split("#", maxsplit=1)[0]
            if not target or target.startswith(("http://", "https://")):
                continue
            resolved = (document.parent / unquote(target)).resolve()
            assert resolved.exists(), f"Broken link in {document}: {raw_target}"
