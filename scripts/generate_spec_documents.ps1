param(
    [ValidateSet("all", "requirements", "design")]
    [string]$DocumentKind = "all"
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$wdFormatDocumentDefault = 16
$wdDoNotSaveChanges = 0
$wdPageBreak = 7
$wdStatisticPages = 2
$wdAutoFitWindow = 2

function New-Row {
    param([object[]]$Cells)
    return [pscustomobject]@{ Cells = $Cells }
}

function Set-CellText {
    param($Table, [int]$Row, [int]$Column, [string]$Text)
    $Table.Cell($Row, $Column).Range.Text = $Text
}

function Add-Paragraph {
    param(
        $Document,
        [string]$Text,
        [string]$Style = "正文",
        [bool]$Bold = $false,
        [bool]$Center = $false
    )
    $range = $Document.Range($Document.Content.End - 1, $Document.Content.End - 1)
    $range.Text = $Text + "`r"
    $paragraph = $range.Paragraphs.Item(1)
    try { $paragraph.Style = $Style } catch { $paragraph.Style = "正文" }
    $paragraph.Range.Font.Bold = if ($Bold) { -1 } else { 0 }
    if ($Center) { $paragraph.Alignment = 1 }
}

function Add-Heading {
    param($Document, [string]$Text, [int]$Level)
    $style = "标题 $Level"
    $range = $Document.Range($Document.Content.End - 1, $Document.Content.End - 1)
    $range.Text = $Text + "`r"
    $paragraph = $range.Paragraphs.Item(1)
    try { $paragraph.Style = $style } catch { $paragraph.Style = "正文" }
    if ($Level -eq 1) { $paragraph.PageBreakBefore = -1 }
    $paragraph.KeepWithNext = -1
}

function Add-Bullet {
    param($Document, [string]$Text)
    Add-Paragraph -Document $Document -Text ("• " + $Text)
}

function Add-Numbered {
    param($Document, [int]$Number, [string]$Text)
    Add-Paragraph -Document $Document -Text ("$Number. $Text")
}

function Add-Caption {
    param($Document, [string]$Text)
    Add-Paragraph -Document $Document -Text $Text -Bold $true -Center $true
}

function Add-Flow {
    param($Document, [string]$Text)
    $range = $Document.Range($Document.Content.End - 1, $Document.Content.End - 1)
    $range.Text = $Text + "`r"
    $paragraph = $range.Paragraphs.Item(1)
    $paragraph.Style = "正文"
    $paragraph.Range.Font.Name = "Consolas"
    $paragraph.Range.Font.NameFarEast = "等线"
    $paragraph.Range.Font.Size = 9
    $paragraph.Range.ParagraphFormat.LeftIndent = 18
    $paragraph.Range.ParagraphFormat.RightIndent = 18
    $paragraph.Range.ParagraphFormat.SpaceBefore = 6
    $paragraph.Range.ParagraphFormat.SpaceAfter = 6
    $paragraph.Range.Shading.BackgroundPatternColor = 15132390
}

function Add-Note {
    param($Document, [string]$Text)
    $range = $Document.Range($Document.Content.End - 1, $Document.Content.End - 1)
    $range.Text = $Text + "`r"
    $paragraph = $range.Paragraphs.Item(1)
    $paragraph.Style = "正文"
    $paragraph.Range.Font.Bold = -1
    $paragraph.Range.Shading.BackgroundPatternColor = 13434879
    $paragraph.Range.ParagraphFormat.LeftIndent = 12
    $paragraph.Range.ParagraphFormat.RightIndent = 12
    $paragraph.Range.ParagraphFormat.SpaceBefore = 6
    $paragraph.Range.ParagraphFormat.SpaceAfter = 6
}

function Add-Table {
    param(
        $Document,
        [string[]]$Headers,
        [object[]]$Rows,
        [bool]$BoldFirstColumn = $false,
        [double[]]$ColumnWidths = @()
    )
    $insert = $Document.Range($Document.Content.End - 1, $Document.Content.End - 1)
    $table = $Document.Tables.Add($insert, $Rows.Count + 1, $Headers.Count)
    try { $table.Style = "网格型" } catch { $table.Borders.Enable = 1 }
    if ($ColumnWidths.Count -eq $Headers.Count) {
        $table.AllowAutoFit = 0
        for ($column = 1; $column -le $Headers.Count; $column++) {
            $table.Columns.Item($column).Width = $ColumnWidths[$column - 1]
        }
    } else {
        $table.AutoFitBehavior($wdAutoFitWindow)
    }
    $table.Rows.Item(1).HeadingFormat = -1
    for ($column = 1; $column -le $Headers.Count; $column++) {
        Set-CellText -Table $table -Row 1 -Column $column -Text ([string]$Headers[$column - 1])
        $table.Cell(1, $column).Range.Font.Bold = -1
        $table.Cell(1, $column).Range.Shading.BackgroundPatternColor = 14277081
    }
    for ($rowIndex = 0; $rowIndex -lt $Rows.Count; $rowIndex++) {
        $cells = $Rows[$rowIndex].Cells
        for ($column = 1; $column -le $Headers.Count; $column++) {
            $value = if ($column -le $cells.Count) { [string]$cells[$column - 1] } else { "" }
            Set-CellText -Table $table -Row ($rowIndex + 2) -Column $column -Text $value
        }
        if ($BoldFirstColumn) { $table.Cell($rowIndex + 2, 1).Range.Font.Bold = -1 }
    }
    $table.Range.Font.NameFarEast = "宋体"
    $table.Range.Font.Name = "Arial"
    $table.Range.Font.Size = 9
    $table.Range.ParagraphFormat.SpaceBefore = 0
    $table.Range.ParagraphFormat.SpaceAfter = 0
    $table.Range.ParagraphFormat.LineSpacingRule = 0
    $table.Range.InsertParagraphAfter()
}

function Add-KeyValueTable {
    param($Document, [object[]]$Rows)
    Add-Table -Document $Document -Headers @("要素", "说明") -Rows $Rows -BoldFirstColumn $true -ColumnWidths @(90, 360)
}

function Add-PageBreak {
    param($Document)
    $range = $Document.Range($Document.Content.End - 1, $Document.Content.End - 1)
    $range.InsertBreak($wdPageBreak)
}

function Replace-ParagraphText {
    param($Document, [string]$OldText, [string]$NewText)
    foreach ($paragraph in $Document.Paragraphs) {
        $text = ($paragraph.Range.Text -replace "[\r\a\v]", "").Trim()
        if ($text -eq $OldText) {
            $paragraph.Range.Text = $NewText + "`r"
            return
        }
    }
}

function Reset-TemplateBody {
    param($Document)
    $start = $null
    foreach ($paragraph in $Document.Paragraphs) {
        $text = ($paragraph.Range.Text -replace "[\r\a\v]", "").Trim()
        $styleName = ""
        try { $styleName = $paragraph.Range.Style.NameLocal } catch { }
        if ($styleName -eq "标题 1" -and $text -eq "研发背景") {
            $start = $paragraph.Range.Start
            break
        }
    }
    if ($null -eq $start) { throw "Cannot locate template body start." }
    $Document.Range($start, $Document.Content.End - 1).Delete()
}

function Configure-DocumentStyles {
    param($Document)
    $Document.PageSetup.TopMargin = 70.9
    $Document.PageSetup.BottomMargin = 70.9
    $Document.PageSetup.LeftMargin = 70.9
    $Document.PageSetup.RightMargin = 70.9
    $Document.PageSetup.HeaderDistance = 42.5
    $Document.PageSetup.FooterDistance = 42.5

    $normal = $Document.Styles.Item("正文")
    $normal.Font.NameFarEast = "宋体"
    $normal.Font.Name = "Arial"
    $normal.Font.Size = 10.5
    $normal.ParagraphFormat.LineSpacingRule = 1
    $normal.ParagraphFormat.SpaceAfter = 6

    foreach ($level in 1..4) {
        $style = $Document.Styles.Item("标题 $level")
        $style.Font.NameFarEast = "黑体"
        $style.Font.Name = "Arial"
        $style.Font.Bold = -1
        $style.Font.Size = @(16, 14, 12, 11)[$level - 1]
        $style.ParagraphFormat.SpaceBefore = if ($level -eq 1) { 12 } else { 8 }
        $style.ParagraphFormat.SpaceAfter = 6
        $style.ParagraphFormat.KeepWithNext = -1
    }
}

function Set-FrontMatter {
    param($Document, [ValidateSet("requirements", "design")] [string]$Kind)
    $isRequirements = $Kind -eq "requirements"
    $documentName = if ($isRequirements) { "需求规格说明书" } else { "设计说明书" }
    $fullTitle = if ($isRequirements) {
        "家健镜 HomeCare Twin 项目需求规格说明书"
    } else {
        "家健镜 HomeCare Twin 软件设计说明书"
    }

    $cover = $Document.Tables.Item(1)
    Set-CellText -Table $cover -Row 2 -Column 1 -Text "家健镜 HomeCare Twin"
    Set-CellText -Table $cover -Row 2 -Column 2 -Text "内部公开"
    Set-CellText -Table $cover -Row 4 -Column 1 -Text "P0 V1.0"

    if ($isRequirements) {
        Replace-ParagraphText -Document $Document -OldText "XXXXXXXX项目" -NewText "家健镜 HomeCare Twin 项目"
        Replace-ParagraphText -Document $Document -OldText "需求说明书" -NewText $documentName
    } else {
        Replace-ParagraphText -Document $Document -OldText "XXXX产品软件设计说明书" -NewText $fullTitle
    }

    $signature = $Document.Tables.Item(2)
    Set-CellText -Table $signature -Row 1 -Column 2 -Text "项目组"
    Set-CellText -Table $signature -Row 1 -Column 4 -Text "2026/08/10"
    Set-CellText -Table $signature -Row 2 -Column 2 -Text "Meyt1n"
    Set-CellText -Table $signature -Row 2 -Column 4 -Text "2026/08/10"
    Set-CellText -Table $signature -Row 3 -Column 2 -Text "Meyt1n"
    Set-CellText -Table $signature -Row 3 -Column 4 -Text "2026/08/10"

    $revision = $Document.Tables.Item(3)
    Set-CellText -Table $revision -Row 2 -Column 1 -Text "1.0"
    Set-CellText -Table $revision -Row 2 -Column 2 -Text "2026/08/10"
    Set-CellText -Table $revision -Row 2 -Column 3 -Text "形成 P0 $documentName 正式交付稿；明确需求、设计、验收边界与当前状态"
    Set-CellText -Table $revision -Row 2 -Column 4 -Text "HomeCare Twin 项目组"
    for ($row = 3; $row -le 5; $row++) {
        for ($column = 1; $column -le 4; $column++) {
            Set-CellText -Table $revision -Row $row -Column $column -Text ""
        }
    }

    foreach ($section in $Document.Sections) {
        foreach ($header in $section.Headers) {
            if (-not $header.Exists) { continue }
            if ($isRequirements) {
                $find = $header.Range.Find
                [void]$find.Execute("xxxx 项目需求说明书", $false, $false, $false, $false, $false, $true, 1, $false, "家健镜项目需求规格说明书", 2)
                $find = $header.Range.Find
                [void]$find.Execute("xxxx项目需求说明书", $false, $false, $false, $false, $false, $true, 1, $false, "家健镜项目需求规格说明书", 2)
            } else {
                $find = $header.Range.Find
                [void]$find.Execute("软件设计说明书", $false, $false, $false, $false, $false, $true, 1, $false, "家健镜项目软件设计说明书", 2)
            }
        }
    }
}

function Add-RequirementsBody {
    param($Document)

    Add-Heading $Document "研发背景" 1
    Add-Paragraph $Document "家健镜 HomeCare Twin 是面向八周软件工程实训的本地优先家庭居家照护教学演示系统。家庭中的药品、过敏、疾病、指标、健康文档、计划和照护关系通常分散在不同载体中，并随时间持续变化。系统以主动录入和人工确认为入口，把每次变化保存为不可覆盖的健康事件，再重建成员当前状态、计算确定性风险规则并形成可处理的照护任务。"
    Add-Paragraph $Document "产品处理的是家庭健康运营过程，不模拟人体生理，不预测疾病，不替代医生或药师。系统不得诊断、开具处方、决定停药、换药或调整剂量，也不提供购药、问诊、广告、佣金或健康消费导流。紧急情况只提供明确求助提示。"
    Add-Note $Document "文档状态：P0 V1.0 需求基线。目标能力使用“应/必须”表达；当前交付状态单独列示，未通过合并、自动测试、人工验收和版本证据的能力不得解读为已完成。"

    Add-Heading $Document "项目目标" 2
    Add-Bullet $Document "建立家庭、成员、照护关系、字段级授权和最小审计，使本人、家庭 Owner 与非 Owner 照护者的访问边界可验证、可撤回。"
    Add-Bullet $Document "建立追加写健康事件、事务 outbox、状态投影、checkpoint 与重放机制，使事实更正和故障恢复可解释。"
    Add-Bullet $Document "完成 OCR-first 的多证据视觉录入与人工复核链，使未知、冲突和低质量结果不会自动成为健康事实。"
    Add-Bullet $Document "用版本化确定性规则生成风险等级和告警预算结果，用本地检索与受约束模型解释证据。"
    Add-Bullet $Document "形成计划确认、延期、跳过、授权照护升级、困难样本回流和模型回滚的双闭环。"

    Add-Heading $Document "产品硬边界" 2
    Add-Table $Document @("边界", "必须满足", "禁止行为") @(
        (New-Row @("本地隐私", "家庭版健康数据、媒体、向量、对话和模型上下文默认留在家庭可信域", "依赖故障时把健康上下文自动转发到云端")),
        (New-Row @("视觉确认", "OCR、条码、包装和主数据共同形成候选，人工确认或修正后才写入正式状态", "以整盒分类结果、单一置信度或未知强制映射替代确认")),
        (New-Row @("家庭授权", "按家庭、成员、字段、动作、目的、期限和升级条件校验", "因亲属或照护者身份默认开放全部健康正文")),
        (New-Row @("风险与提醒", "规则决定风险，普通告警合并并受预算控制，严重事项不被压制", "由 LLM 修改风险等级、医嘱、频次或剂量")),
        (New-Row @("证据解释", "回答展示事实、规则、引用、确认状态和版本；证据不足则澄清或拒答", "输出无来源的肯定性医疗结论")),
        (New-Row @("业务范围", "只提供家庭居家照护教学流程", "买药、问诊、广告、佣金或医疗服务转化"))
    )

    Add-Heading $Document "当前交付状态" 2
    Add-Paragraph $Document "截至 2026-08-10，范围与十页信息架构、资源原型、工程骨架、家庭/成员/授权能力已有合并与验收记录；事件补偿、幂等、outbox 和投影重放在需求追踪矩阵中仍为待验收。当前分支包含视觉任务、人工复核、文件、认证、规则、计划、时间线和风险查询等代码及部分测试，但这些代码出现不等同于完整业务验收。正式视觉模型与授权数据集、完整关系图谱、版本化规则库、RAG/Ollama 助手、十页完整前端和最终部署验收仍未完成。"
    Add-Table $Document @("能力域", "需求状态口径", "文档中的处理方式") @(
        (New-Row @("范围、架构、工程骨架", "已有可定位合并/评审证据", "可描述为已形成基线")),
        (New-Row @("家庭、成员、字段授权", "HCT-102 已验证，生产身份与完整字段视图仍需后续 Story", "只陈述已验收边界，不扩大到完整身份体系")),
        (New-Row @("不可变事件与恢复", "HCT-103 待验收", "描述设计与现有接口，不声明最终验收")),
        (New-Row @("视觉任务与人工复核", "当前分支有迁移、接口和测试，追踪状态未形成完整验收", "列为实现中增量，模型质量仍按固定集验收")),
        (New-Row @("规则、计划、助手、大屏、训练", "完整 P0 未交付", "仅写需求和设计约束"))
    )

    Add-Heading $Document "用户对象" 1
    Add-Table $Document @("用户角色", "主要目标", "允许范围", "明确限制") @(
        (New-Row @("家庭成员", "录入并确认自己的健康事实，处理任务和查看证据", "自己及明确授权的成员数据", "不能读取其他家庭或未授权成员信息")),
        (New-Row @("家庭 Owner", "创建家庭、维护成员目录、管理家庭授权和本家庭事件", "由 household.created_by 标识的本家庭管理范围", "不能跨家庭访问；不得把家庭关系推断成其他家庭权限")),
        (New-Row @("非 Owner 照护者", "处理被委托成员的任务、计划和风险", "授权成员、字段、动作、目的和有效期内的最小范围", "亲属/照护者角色名称本身不产生访问权")),
        (New-Row @("数据/知识管理员", "审核主数据、规则、知识和困难样本", "脱敏数据、版本登记和发布流程", "不因管理资料而自动获得家庭健康正文")),
        (New-Row @("模型/系统管理员", "训练、评测、部署、监控和回滚技术制品", "模型指标、资源、版本和已授权训练数据", "家庭端不自动训练；管理员不自动拥有成员数据权限")),
        (New-Row @("测试/验收人员", "执行固定集、E2E、安全、部署和回滚验收", "合成、公开许可或明确授权数据", "不能用真实未授权数据和截图替代可复现证据"))
    )

    Add-Heading $Document "典型使用场景" 2
    Add-Table $Document @("场景", "触发", "用户价值", "成功边界") @(
        (New-Row @("新增药品", "成员拍摄药盒或上传短视频", "减少药名、规格、批次和有效期的手工录入错误", "多证据候选经人工确认后形成健康事件")),
        (New-Row @("识别冲突", "OCR、条码、规格或包装证据不一致", "让不确定性显式进入复核", "CONFLICT 不进入正式状态，修正保留 before/after")),
        (New-Row @("家庭协同", "成员授权照护者查看摘要或处理提醒", "照护者在必要范围内协助", "撤权/过期立即拒绝，API 执行字段过滤")),
        (New-Row @("风险提示", "已确认事实命中版本化规则", "解释为何出现提醒以及下一步由谁确认", "严重事项不受普通预算压制，不给停药/剂量结论")),
        (New-Row @("计划响应", "提醒到期或连续未确认", "支持确认、延期、跳过和照护升级", "不得越过安全时间窗或升级给无授权对象")),
        (New-Row @("证据问答", "用户询问当前记录、规则或文档依据", "获得可核对的通俗解释", "无证据/越权/危险医疗请求受控拒答")),
        (New-Row @("删除与撤权", "用户撤回授权或发起删除", "控制数据全生命周期", "主库、文件、索引、缓存和可控备份有处置状态"))
    )

    Add-Heading $Document "应用范围" 1
    Add-Heading $Document "P0 范围" 2
    Add-Table $Document @("功能域", "P0 交付范围", "规模或约束") @(
        (New-Row @("家庭健康事件中心", "家庭、成员、授权、疾病、过敏、指标、药物、库存、计划、文档和事件时间线", "MySQL 为唯一事实主库；更正追加补偿事件")),
        (New-Row @("多证据视觉录入", "图片/短视频质量检查、全图 OCR、包装/条码辅助定位、条码解码、候选融合和人工复核", "12–20 种受控药品 SKU；允许 UNKNOWN/CONFLICT/REVIEW")),
        (New-Row @("关系投影", "成员—疾病—过敏—药品—成分—批次—计划—照护者关系", "从已确认事实重建，P0 不以 Neo4j 为事实源")),
        (New-Row @("风险与提醒", "过期、临期、低库存、重复成分、登记过敏和 30–50 组审核规则", "四级提醒；普通预算；严重事项不压制")),
        (New-Row @("照护计划", "医嘱事实、计划版本、确认/延期/跳过、授权升级", "只优化提醒策略，不改变药物和剂量")),
        (New-Row @("环境行动卡", "粗粒度天气输入和低风险生活行动提示", "只发送城市/区县代码；失败不阻塞核心链路")),
        (New-Row @("本地证据助手", "SQL/图谱/规则/RAG 工具调用、引用解释、拒答和结构化降级", "家庭版不使用云端健康上下文回退")),
        (New-Row @("大屏与模型实验室", "家庭任务/趋势/运行状态和模型版本/指标/回滚状态", "聚合信息不得含真实健康正文")),
        (New-Row @("困难样本与训练", "纠错、授权审核、追加训练、固定集 V1/V2 对照和发布回滚", "训练与家庭运行分离；模型权重不进入 Git"))
    )

    Add-Heading $Document "非目标" 2
    Add-Bullet $Document "不接入医院 HIS、全量可穿戴设备、国家药品追溯平台真实业务或在线诊疗服务。"
    Add-Bullet $Document "不承诺识别任意药品，不建设完整医学本体、完整相互作用数据库或生理数字孪生。"
    Add-Bullet $Document "不做人脸身份入口和持续家庭摄像头监控，不自动确认成员已经服药。"
    Add-Bullet $Document "不以课程演示推断疾病结局，不使用“治愈率提升”等临床效果指标。"
    Add-Bullet $Document "不提供买药、挂号、问诊、保险、广告、佣金链接或健康消费推荐。"

    Add-Heading $Document "术语定义" 1
    Add-Table $Document @("术语", "释义") @(
        (New-Row @("家庭可信域", "家庭局域网或机构内网中受控运行的 Web、API、数据库、文件、视觉/OCR、向量索引和 Ollama 环境；默认拒绝健康数据网络出口。")),
        (New-Row @("家庭健康运营型数字孪生", "用事件、当前状态和关系投影表达家庭健康事实的变化与照护过程，不模拟人体生理。")),
        (New-Row @("Owner", "由 household.created_by 标识的当前单家庭管理员，只在其创建的家庭内拥有管理范围。")),
        (New-Row @("非 Owner 照护者", "必须通过成员、字段、动作、目的和有效期授权才能访问的协作人员。")),
        (New-Row @("RBAC/ABAC", "RBAC 定义角色上限；ABAC 再校验家庭、成员、字段、动作、目的、时间和授权状态。")),
        (New-Row @("health_event", "追加写健康事件；记录变化、来源、操作者、确认状态、证据、序号和版本，不允许原地覆盖。")),
        (New-Row @("补偿事件", "用于更正上一已确认事件的新事件，通过 supersedes/causation 关系保留历史。")),
        (New-Row @("事务 outbox", "与健康事件同事务写入的最小派发记录，用于可靠触发投影和后续消费者，不复制健康正文。")),
        (New-Row @("状态投影", "由已确认事件按成员序号归约得到的当前状态，可从空状态或 checkpoint 重建。")),
        (New-Row @("OCR-first", "先做全图 OCR 并保留文字框原值，再用 YOLO 辅助包装/条码定位，由专用解码器读取码值。")),
        (New-Row @("MATCHED", "多证据一致且候选明确；仍需人工确认。")),
        (New-Row @("CONFLICT", "条码、OCR、规格、日期、包装或主数据互相矛盾；必须复核。")),
        (New-Row @("UNKNOWN", "开放集未知或没有可靠候选；允许手工录入或补拍。")),
        (New-Row @("REVIEW", "质量不足、字段缺失或候选间隔不足，需要人工补录/复核。")),
        (New-Row @("证据契约", "回答或风险卡必须同时携带事实、规则、文档引用、确认状态、可见范围和版本。")),
        (New-Row @("告警预算", "对 INFO/GENERAL 进行合并、摘要和每日限量的机制；不得压制 HIGH/URGENT。")),
        (New-Row @("RAG", "先进行身份和权限过滤，再从版本化本地知识片段检索证据；检索结果不直接成为医疗结论。")),
        (New-Row @("困难样本", "保留原预测、人工修正、错误类型、模型版本和训练同意状态的受控样本。")),
        (New-Row @("P0", "八周课程交付的优先级范围；只有证据齐全的条目才可标记已验证。"))
    )

    Add-Heading $Document "业务流程说明" 1
    Add-Heading $Document "整体业务流程" 2
    Add-Flow $Document "主动拍照/上传/手工录入`n  ↓`n本地质量检查与证据提取`n  ↓`nMATCHED / CONFLICT / UNKNOWN / REVIEW`n  ↓`n本人或获权复核者确认、修正或拒绝`n  ↓`n追加 health_event + outbox + 在线投影（同一事务）`n  ↓`n关系投影与版本化规则计算`n  ↓`n风险卡、计划任务和权限过滤后的证据检索`n  ↓`n本地模型解释或结构化降级`n  ↓`n本人/照护者确认行动、审计、困难样本回流"
    Add-Paragraph $Document "流程中的模型输出只作为候选或语言解释。正式健康事实必须由用户或授权复核者确认；风险等级只能由确定性规则生成；检索为空、权限不足或依赖不可用时必须停在明确的待复核、拒答或降级状态。"

    Add-Heading $Document "家庭创建、授权与访问流程" 2
    Add-Flow $Document "身份认证 → 选择家庭 → 校验 Owner/非 Owner → 校验成员 → 校验字段与动作 → 校验 X-Access-Purpose → 校验有效期/撤权 → 返回过滤后的结果并写最小审计"
    Add-Numbered $Document 1 "Owner 由 household.created_by 判定，只能管理自己创建的家庭。"
    Add-Numbered $Document 2 "非 Owner 必须提交稳定的 ASCII 目的代码；展示文案不能代替目的代码。"
    Add-Numbered $Document 3 "跨家庭、未授权以及资源 ID 猜测统一返回隐藏式 404，详细原因只进入本地脱敏审计。"
    Add-Numbered $Document 4 "授权更新和撤回必须携带 expected_version；版本冲突返回 409，已撤销授权不可再次修改。"

    Add-Heading $Document "视觉录入与人工复核流程" 2
    Add-Flow $Document "选择成员 → 上传图片/短视频 → MIME/大小/像素/时长与恶意内容检查 → 清晰度/曝光/反光/方向/透视 → 全图 OCR → YOLO 包装/条码辅助 → 条码专用解码 → 规则/词典/本地字段结构化 → 多证据候选 → 四态 → 人工确认/修正/拒绝 → 正式事件"
    Add-Table $Document @("状态", "进入条件", "允许动作", "禁止动作") @(
        (New-Row @("MATCHED", "证据一致且超过校准阈值", "查看证据、确认或修正", "不经确认直接进入风险计算")),
        (New-Row @("CONFLICT", "关键证据相互矛盾", "强制复核、修正、补拍或拒绝", "默认选择最高分候选")),
        (New-Row @("UNKNOWN", "无可靠候选或开放集未知", "手工录入、补拍或拒绝", "强制映射到已知 SKU")),
        (New-Row @("REVIEW", "质量低、字段缺失或候选间隔不足", "补录、补拍、人工选择", "显示假置信度或成功状态")),
        (New-Row @("CONFIRMED/CORRECTED", "复核人完成确认或修正", "写入正式事件并触发投影", "覆盖原预测和修正原因"))
    )

    Add-Heading $Document "事件、投影与故障恢复流程" 2
    Add-Flow $Document "写请求 + Idempotency-Key → 规范请求指纹 → 锁定成员并分配 sequence_no → 写 health_event → 写最小 outbox → 更新在线投影 → 提交`nworker: PENDING → PROCESSING → DISPATCHED；失败为 FAILED，过期锁可回收`n恢复: 空状态或 checkpoint → 校验 SHA-256 → 按 sequence_no 重放 → 比较在线 state_hash"
    Add-Paragraph $Document "相同家庭、幂等键、操作、操作者和规范请求体应返回原事件；同键不同指纹必须冲突。缺失已确认前序时保持 OUT_OF_ORDER，重复投递不得重复增加投影效果。"

    Add-Heading $Document "风险、计划与照护升级流程" 2
    Add-Flow $Document "已确认状态 → 规则版本与适用范围校验 → 过期/库存/重复/过敏/有限相互作用规则 → 去重键 → INFO/GENERAL 预算 → HIGH/URGENT 豁免 → 风险证据卡 → 确认/延期/跳过 → 连续未确认时校验照护授权并升级"
    Add-Paragraph $Document "计划页面必须区分只读的医嘱事实与可调整的提醒策略。任何提醒建议不得越过安全时间窗，不得创建、停用、替换药物或改变剂量、频次。"

    Add-Heading $Document "本地证据助手流程" 2
    Add-Flow $Document "登录与成员授权 → 意图/风险路由 → SQL/图谱/规则/RAG 工具 → 结构化证据上下文 → Ollama → Schema 校验 → 工具绑定与引用可访问性 → 主张忠实性 → 医疗禁止内容/无导流/紧急升级校验 → 回答或受控拒答"
    Add-Paragraph $Document "向量库或 Ollama 不可用时，系统应停止自然语言证据回答，只展示可核验的结构化事实、规则、引用和任务；不得使用外部云模型补答。"

    Add-Heading $Document "撤权、导出与删除流程" 2
    Add-Flow $Document "用户确认范围与目的 → 二次确认 → 撤权或删除任务 → API 立即拒绝新访问/升级 → 清理主库业务对象、文件、向量索引和缓存 → 记录可控备份到期处置 → 保留不含健康正文的最小审计证明"

    Add-Heading $Document "需求规格说明" 1
    Add-Heading $Document "身份、家庭与授权（FR-01）" 2
    Add-KeyValueTable $Document @(
        (New-Row @("目标", "提供本地账号、家庭、成员、照护关系和可撤回的字段级授权；支持密码登录以及 PIN/二维码二次确认。")),
        (New-Row @("前置条件", "操作者已认证；创建授权时为本家庭 Owner；被授权人、成员和目的均有效。")),
        (New-Row @("输入", "家庭名称、成员显示名/角色/actor_id、被授权人、数据字段、动作、ASCII 目的代码、有效期、expected_version。")),
        (New-Row @("处理规则", "Owner 只管理自己的家庭；非 Owner 同时通过家庭、成员、字段、动作、目的、期限校验；授权创建版本为 1，更新/撤回采用 compare-and-swap。")),
        (New-Row @("输出", "家庭/成员、当前授权、字段可见范围、授权审计和稳定错误状态。")),
        (New-Row @("异常与安全", "跨家庭、ID 猜测和未授权访问返回隐藏式 404；版本冲突返回 409；审计不记录健康正文；撤权立即生效。")),
        (New-Row @("验收", "跨家庭拒绝率 100%；非 Owner 只返回授权字段；撤权/过期后立即拒绝；敏感读取和授权生命周期有最小审计。")),
        (New-Row @("非目标", "P0 不采用人脸身份；不允许因子女或照护者角色默认看到全部数据。"))
    )

    Add-Heading $Document "家庭健康事件中心（FR-02）" 2
    Add-KeyValueTable $Document @(
        (New-Row @("目标", "以追加写事件管理疾病、过敏、指标、药品、库存、计划、文档和照护关系变化，并可重放恢复当前状态。")),
        (New-Row @("前置条件", "家庭和成员存在；操作者具有写动作与字段权限；正式投影只接收 CONFIRMED 事件。")),
        (New-Row @("输入", "member_id、event_type、source、confirmation_status、payload、evidence、occurred_at、Idempotency-Key。")),
        (New-Row @("处理规则", "分配成员内 sequence_no；计算请求指纹；事件、outbox 和在线投影同事务提交；更正追加补偿事件；事件不可 UPDATE/DELETE。")),
        (New-Row @("输出", "事件 ID、序号、发生/记录时间、correlation/causation/supersedes、Schema 版本、投影版本与哈希。")),
        (New-Row @("故障恢复", "worker 回收过期锁；FAILED 可重试；checkpoint 校验失败或乱序返回稳定冲突；存在事件时禁止破坏性 downgrade。")),
        (New-Row @("验收", "相同幂等请求只产生一个事实；冲突指纹拒绝；补偿保留原事件；重复投递无副作用；空状态/checkpoint 重放结果与在线状态一致。")),
        (New-Row @("非目标", "不把 outbox、投影、图谱或向量索引作为第二事实源。"))
    )

    Add-Heading $Document "多证据视觉录入（FR-03）" 2
    Add-KeyValueTable $Document @(
        (New-Row @("目标", "接收图片、浏览器拍照和短视频，完成质量门控、OCR-first 证据提取、候选融合和四态输出。")),
        (New-Row @("前置条件", "用户主动触发；文件通过类型、大小、像素、时长和内容探测；成员访问权限有效。")),
        (New-Row @("输入", "本地文件引用、成员、任务类型、幂等键、模型阈值及代码/数据/模型版本。")),
        (New-Row @("处理规则", "全图 OCR 保存原始 token/区域/置信度；YOLO 只辅助包装和条码区域；专用解码器读取码值；本地结构化模块只能选择已有证据。")),
        (New-Row @("输出", "MATCHED/CONFLICT/UNKNOWN/REVIEW、证据帧、OCR 框、条码、包装特征、候选、版本、耗时和错误码。")),
        (New-Row @("人工复核", "确认、修正或拒绝；修正保存原候选、after、原因、操作者、时间和独立训练同意。")),
        (New-Row @("异常与降级", "视觉/OCR 不可用时保留任务并允许手工录入；冲突/未知/低质量不进入正式状态和规则。")),
        (New-Row @("验收", "自动通过精确率≥99%；未知 SKU 转人工率≥95%；字段来源完整率 100%；只有 CONFIRMED/CORRECTED 触发正式事件。")),
        (New-Row @("非目标", "不承诺识别任意药品，不以 YOLO 单独识别 SKU，不使用模型补造图片文字。"))
    )

    Add-Heading $Document "家庭健康关系投影（FR-04）" 2
    Add-KeyValueTable $Document @(
        (New-Row @("目标", "展示成员、疾病、过敏、药品、成分、批次、计划、文档和照护者关系。")),
        (New-Row @("输入", "已确认事件、成员状态和当前授权范围。")),
        (New-Row @("处理规则", "从 MySQL 事实重建；每个节点和边关联来源事件、确认状态和更新时间；更正/撤销后重算。")),
        (New-Row @("输出", "权限过滤后的节点、边、来源事件和重建状态。")),
        (New-Row @("异常与降级", "投影异常时停止展示可能过期的敏感缓存，提供重建入口；撤权后隐藏受影响节点与聚合数量。")),
        (New-Row @("验收", "事件确认后关系更新；补偿后关系一致；未确认四态不生成正式节点；每条边可追溯。")),
        (New-Row @("非目标", "P0 不引入大型医学本体或让图数据库成为事实源。"))
    )

    Add-Heading $Document "风险规则与告警预算（FR-05）" 2
    Add-KeyValueTable $Document @(
        (New-Row @("目标", "对过期、临期、低库存、重复成分、登记过敏和有限审核规则产生可解释风险。")),
        (New-Row @("前置条件", "参与事实已人工确认；规则有来源、版本、范围、有效期、正反例和回滚版本。")),
        (New-Row @("输入", "成员当前状态、规则版本、告警预算、去重窗口和授权上下文。")),
        (New-Row @("处理规则", "规则引擎独占等级决定权；同类告警按成员/规则/时间窗合并；INFO/GENERAL 受预算控制，HIGH/URGENT 不受普通预算压制。")),
        (New-Row @("输出", "等级、rule_id/version、参与事实、证据、覆盖范围、去重键、有效期、预算决定和处理角色。")),
        (New-Row @("异常与安全", "规则版本不匹配时停止发布；证据不足进入待确认；不得输出‘可以一起吃’或‘必须停药’。")),
        (New-Row @("验收", "规则单测 100%；已知严重案例漏报为 0；普通预算执行率 100%；风险证据/版本完整率 100%。")),
        (New-Row @("非目标", "不提供完整临床决策支持，不由模型创建或批准医疗规则。"))
    )

    Add-Heading $Document "计划、确认与照护升级（FR-06）" 2
    Add-KeyValueTable $Document @(
        (New-Row @("目标", "围绕已确认医嘱事实形成可审计的提醒策略和照护响应。")),
        (New-Row @("输入", "计划版本、医嘱事实、安全时间窗、提醒策略、确认/延期/跳过及原因、照护授权。")),
        (New-Row @("处理规则", "医嘱事实只读；提醒时间和渠道只能在安全时间窗内调整；新医嘱未经人工批准不得切换；连续未确认后再校验升级授权。")),
        (New-Row @("输出", "计划版本差异、确认状态、处理原因、升级对象、授权依据和审计事件。")),
        (New-Row @("异常与安全", "越界建议被阻止；升级对象无授权或已撤权时不通知；部分失败不得保存半成品变更。")),
        (New-Row @("验收", "确认/延期/跳过可追踪率 100%；越过安全时间窗的建议 100% 阻止；升级对象授权有效；批准记录完整。")),
        (New-Row @("非目标", "系统不得新增、停用、替换药物或改变剂量、频次。"))
    )

    Add-Heading $Document "环境行动卡（FR-07）" 2
    Add-KeyValueTable $Document @(
        (New-Row @("目标", "使用粗粒度天气信息生成低风险生活安排提示。")),
        (New-Row @("输入", "城市/区县编码、温度、温差、降雨、空气质量、紫外线和可用花粉等级。")),
        (New-Row @("处理规则", "出口仅允许白名单天气适配器和城市编码；结合成员主动授权标签；同一事件有效期内只生成一次。")),
        (New-Row @("输出", "环境事件、行动卡、来源时间、有效期和降级状态。")),
        (New-Row @("异常与降级", "天气失败时不生成新卡，不影响档案、事件、规则和任务；不缓存未授权健康字段。")),
        (New-Row @("验收", "外部请求不含成员、药品、疾病、过敏、报告、图片或对话；不推断疾病，不触发用药更改。"))
    )

    Add-Heading $Document "本地证据型助手（FR-08）" 2
    Add-KeyValueTable $Document @(
        (New-Row @("目标", "调用授权、SQL、关系投影、规则和 RAG 工具，对当前事实进行有引用的通俗解释。")),
        (New-Row @("前置条件", "操作者与成员权限有效；知识来源、许可、版本、哈希和权限域已登记。")),
        (New-Row @("输入", "问题、当前成员、目的、可见字段、事实/规则/文档工具结果和模型/知识版本。")),
        (New-Row @("处理规则", "检索前过滤权限；模型不直连全库或向量库；后端依次校验 Schema、工具绑定、引用、忠实性、规则不可改写、授权、医疗禁止内容和无导流。")),
        (New-Row @("输出", "route、answer、facts、rules、citations、actions、visibility、model_version、knowledge_version、request_id。")),
        (New-Row @("异常与降级", "无证据时澄清/拒答；模型或向量库不可用时返回结构化事实/规则卡或 MODEL_UNAVAILABLE；不使用云端回退。")),
        (New-Row @("验收", "引用存在率 100%；无证据拒答率≥95%；越权与危险医疗请求拒绝率≥98%；无授权字段返回率和商业导流响应率均为 0%。")),
        (New-Row @("非目标", "不诊断、处方、停药、换药、调剂量，不让模型批准计划或规则。"))
    )

    Add-Heading $Document "家庭大屏与模型实验室（FR-09）" 2
    Add-KeyValueTable $Document @(
        (New-Row @("目标", "家庭大屏展示非敏感聚合与任务；模型实验室展示数据、模型、阈值、固定集指标、发布和回滚状态。")),
        (New-Row @("输入", "授权后的任务/风险聚合、事件趋势、运行状态、模型登记、评估结果和制品哈希。")),
        (New-Row @("处理规则", "公共大屏默认不展示姓名、病史、药品详情、报告图片和对话；模型管理员权限不转化为家庭数据权限。")),
        (New-Row @("输出", "今日任务、近期变化、告警预算、照护响应、依赖状态；模型版本、指标、失败样本、部署/回滚状态。")),
        (New-Row @("异常与降级", "失败指标隐藏并标注最后更新时间；指标/评估不足时保持候选状态，不允许发布。")),
        (New-Row @("验收", "聚合不含真实身份或健康正文；未确认数据不进入趋势/成功指标；非管理员不能查看模型详情。"))
    )

    Add-Heading $Document "困难样本与追加训练（FR-10）" 2
    Add-KeyValueTable $Document @(
        (New-Row @("目标", "把人工纠错转化为经过授权、脱敏、审核和可回滚的模型改进证据。")),
        (New-Row @("输入", "原预测、人工修正、错误类型、模型版本、样本授权、训练同意和脱敏状态。")),
        (New-Row @("处理规则", "按实体药盒、采集日期、设备和视频会话分组划分；固定集冻结并记录哈希；V1/V2 使用同一测试集；检查旧类别退化。")),
        (New-Row @("输出", "数据卡、训练批次、模型卡、参数/随机种子/硬件、指标、失败样例、制品哈希、批准和回滚版本。")),
        (New-Row @("异常与安全", "未授权样本不训练；撤回后停止后续训练并清理可控未发布制品；失败实验保留；旧类下降超阈值拒绝发布。")),
        (New-Row @("验收", "训练集无相邻帧泄漏；V2 旧类别最大下降≤2 个百分点；家庭端不自动训练或发布；模型权重不提交到仓库。"))
    )

    Add-Heading $Document "页面与交互需求" 2
    Add-Table $Document @("页面", "首要职责", "关键状态", "强制展示") @(
        (New-Row @("家庭总览", "近期变化、待确认风险、今日任务、本地/授权状态", "正常/加载/空/错误/离线/未授权/低置信", "本地隐私状态、证据入口、授权摘要")),
        (New-Row @("成员健康档案", "显示获权事实、来源、确认和时间线", "字段级未授权与二次确认", "来源事件、最后更新时间、可见范围")),
        (New-Row @("视觉扫描中心", "质量门控、多渠道证据和四态候选", "QUEUED/处理中/四态/失败", "原图/帧、OCR、条码、包装、版本")),
        (New-Row @("人工复核中心", "确认、修正、拒绝、训练同意", "待复核/已确认/已修正/已跳过", "before/after、原因、操作者、独立训练同意")),
        (New-Row @("家庭健康图谱", "已确认事实关系投影", "重建/待同步/未授权", "节点边来源事件、确认状态")),
        (New-Row @("用药安全中心", "规则风险和证据", "四级风险/预算/处理状态", "事实、规则、文档、确认、版本")),
        (New-Row @("健康计划中心", "医嘱事实与提醒策略", "确认/延期/跳过/升级", "版本差异、安全时间窗、批准记录")),
        (New-Row @("本地健康助手", "先证据后解释", "检索/工具/拒答/模型降级", "成员、可见范围、引用、免责声明")),
        (New-Row @("家庭健康大屏", "非敏感聚合与运行状态", "公共模式/离线/错误", "任务数量、趋势、授权提示")),
        (New-Row @("模型实验室", "数据模型指标与发布回滚", "候选/评估/已批准/失败/已回滚", "哈希、固定集、失败样本、版本"))
    )
    Add-Paragraph $Document "所有页面必须用文字、图标和颜色共同表达状态；页面不得用旧缓存、假置信度、空白成功或固定回答掩盖依赖故障。授权设置是总览、成员档案和大屏共用的支撑视图，不形成独立的权限口径。"

    Add-Heading $Document "性能需求" 1
    Add-Table $Document @("指标", "P0 目标", "测量约束") @(
        (New-Row @("CPU 单图全流程 P95", "≤ 8 秒", "报告硬件、样本量、冷/热状态、模型/OCR版本")),
        (New-Row @("药品包装 Recall", "≥ 95%", "只评价包装/条码辅助定位，不替代字段识别")),
        (New-Row @("受控集 mAP@0.5", "≥ 90%", "按类别、样本量和置信区间报告")),
        (New-Row @("OCR 文本区域召回率", "≥ 95%", "保留原始文字框和版本")),
        (New-Row @("药名字段原始值保真率", "≥ 95%", "模型不得覆盖原 OCR")),
        (New-Row @("药名字段完全匹配率", "≥ 90%", "使用冻结字段契约")),
        (New-Row @("有效期字段完全匹配率", "≥ 88%", "覆盖不同日期格式和遮挡")),
        (New-Row @("良好图像条码解码率", "≥ 95%", "由专用解码器测量")),
        (New-Row @("自动通过结果精确率", "≥ 99%", "覆盖开放集和相似包装")),
        (New-Row @("意图路由准确率", "≥ 92%", "基础模型与 QLoRA 使用同一盲测集")),
        (New-Row @("工具选择准确率", "≥ 90%", "含越权与无证据场景")),
        (New-Row @("工具参数完全正确率", "≥ 88%", "字段、成员和目的精确匹配")),
        (New-Row @("JSON Schema 合法率", "≥ 98%", "后端校验后统计")),
        (New-Row @("单盒拍摄到确认中位时间", "≤ 60 秒", "包含复核操作但不含用户长时间离开")),
        (New-Row @("重复告警合并率", "≥ 90%", "HIGH/URGENT 不计入普通预算压制"))
    )
    Add-Paragraph $Document "数据库、API 页面加载和并发预算仍须由资源原型与阶段验收冻结；没有测量证据时不写具体毫秒承诺。"

    Add-Heading $Document "可靠性需求" 1
    Add-Table $Document @("故障/风险", "要求行为", "禁止行为", "验收重点") @(
        (New-Row @("重复写请求", "使用幂等键和请求指纹返回原结果或冲突", "重复创建健康事实", "相同/冲突 key 回归")),
        (New-Row @("worker 中断", "回收过期锁，按序重试，稳定错误码", "丢失事件或打印 payload", "FAILED/PROCESSING 恢复")),
        (New-Row @("投影损坏", "从事件或 checkpoint 重建并比较哈希", "用投影反写事实", "空状态和 checkpoint 重放")),
        (New-Row @("视觉/OCR 离线", "任务保留、明确降级、允许手工录入", "返回伪造候选", "依赖故障场景")),
        (New-Row @("向量库离线", "停止证据问答，保留事实和规则", "让模型用常识补答", "MODEL_UNAVAILABLE/结构化降级")),
        (New-Row @("Ollama 离线", "展示结构化事实、规则、引用和任务", "自动转发云端", "无外部网络请求")),
        (New-Row @("天气失败", "不生成新行动卡，不影响核心链", "重复生成或上传健康详情", "超时/无数据")),
        (New-Row @("撤权/删除", "立即拒绝并传播到缓存/索引/通知/可控备份", "继续返回旧缓存", "撤权、删除任务状态")),
        (New-Row @("迁移失败", "保留备份、支持兼容应用或前滚修复", "有事实数据时破坏性降级", "空库/已有数据升级"))
    )

    Add-Heading $Document "安全与隐私需求" 1
    Add-Table $Document @("控制域", "要求") @(
        (New-Row @("数据分级", "D0 公开资料登记来源/许可/哈希；D1 内部数据限团队；D2 健康事实加密并成员级授权；D3 原始报告/视频/密钥/备份单独密钥、最短留存、禁止进日志。")),
        (New-Row @("身份与会话", "密码使用安全哈希；访问令牌短期有效并支持轮换；高敏查看、导出和关键操作要求二次确认；认证失败限流。")),
        (New-Row @("对象授权", "所有成员资源执行家庭边界、Owner/非 Owner、成员、字段、动作、目的、期限和撤权检查；前端隐藏不构成授权。")),
        (New-Row @("上传", "MIME 白名单、扩展与魔数一致、大小/像素/时长限制、随机存储键、路径穿越防护、恶意内容与解压炸弹检查。")),
        (New-Row @("网络出口", "默认拒绝；仅显式白名单适配器可出网；天气只发送城市/区县编码；记录目的、数据分类、授权依据、请求摘要和结果。")),
        (New-Row @("日志与审计", "只记录 request_id、对象 ID、动作、版本和结果；不记录报告正文、完整 OCR、提示词上下文、令牌和模型 payload。")),
        (New-Row @("知识与模型", "知识来源、许可、版本、哈希、权限域和失效时间齐全；文档内提示词视为数据；模型/规则/知识均可回滚。")),
        (New-Row @("事件响应", "泄露、越权、错误规则或危险回答发生时隔离入口/版本、保全最小审计、评估影响、回滚、通知、修复和回归。"))
    )

    Add-Heading $Document "可用性与可访问性需求" 1
    Add-Bullet $Document "基础档在 LLM、向量库、视觉或天气离线时仍能管理家庭事实、授权、事件、规则和任务。"
    Add-Bullet $Document "正常、加载、空、错误、离线、未授权和低置信状态具有稳定尺寸和明确文案，不闪现其他家庭缓存。"
    Add-Bullet $Document "风险、证据、确认和拒答不只依赖颜色；键盘可以完成主要流程；交互控件有可读名称和焦点状态。"
    Add-Bullet $Document "敏感字段被隐藏时只显示未获授权，不泄露该字段是否存在；错误响应提供 request_id 和可执行重试动作。"
    Add-Bullet $Document "所有医疗相关页面显示教学演示边界；危险请求引导联系现有医生、药师或当地急救服务。"

    Add-Heading $Document "运行环境需求" 1
    Add-Heading $Document "硬件环境" 2
    Add-Table $Document @("档位", "最低/建议资源", "适用能力", "当前证据边界") @(
        (New-Row @("基础档", "x64、4 逻辑核、8 GiB RAM、20 GiB 可用磁盘", "Web、API、worker、MySQL、规则、轻量 OCR 和加密文件", "当前设备已完成工程和资源探针；不代表正式视觉性能")),
        (New-Row @("增强档", "建议 16 GiB RAM；7B Q4 模型约需 5 GiB 显存/内存，建议 8 GiB 以上可用显存", "基础档 + 本地向量检索 + Ollama", "qwen2.5:7b 本地握手为资源原型，不等同于助手业务验收")),
        (New-Row @("研发档", "独立 GPU 工作站或受控短时训练资源、授权数据与模型制品存储", "标注、训练、固定集评测和模型登记", "家庭运行机不得自动训练"))
    )

    Add-Heading $Document "软件环境" 2
    Add-Table $Document @("层", "软件基线", "约束") @(
        (New-Row @("客户端", "现代 Chromium 浏览器；Vue 3、TypeScript、Vite、Element Plus、ECharts", "只调用 /api/v1，不直连数据库、向量库或 Ollama")),
        (New-Row @("服务端", "Python 3.11、FastAPI、Pydantic、SQLAlchemy 2、Alembic", "统一授权、事务、证据和输出校验")),
        (New-Row @("事实库", "MySQL 8.4，utf8mb4，UTC", "唯一事实主库；迁移和备份可复现")),
        (New-Row @("视觉", "OpenCV；PaddleOCR/本地 OCR；专用条码库；YOLO11n 辅助", "正式版本、阈值和许可须经固定集验收")),
        (New-Row @("检索/模型", "FAISS 起步，Qdrant 为服务化候选；Ollama 本地量化模型；LLaMA Factory QLoRA", "增强档可选；不得成为事实源或云端默认回退")),
        (New-Row @("部署", "Docker Compose、Nginx、跨平台 start.ps1/start.sh", "内部服务仅本机/容器网络，Nginx 是唯一用户入口")),
        (New-Row @("测试", "pytest、httpx、Playwright、固定视觉/LLM/安全评估集", "测试环境、版本、样本哈希和结果可定位"))
    )

    Add-Heading $Document "验收与需求追踪" 1
    Add-Table $Document @("编号", "验收主题", "核心证据", "发布阻断") @(
        (New-Row @("FR-01", "家庭/字段授权", "跨家庭、Owner/非 Owner、撤权、过期、字段过滤和审计测试", "任一越权或撤权失效")),
        (New-Row @("FR-02", "追加事件与恢复", "幂等、补偿、同事务、重试、乱序、重放、不可变触发器", "事实覆盖、事件丢失或不可重建")),
        (New-Row @("FR-03", "多证据复核", "固定视觉集、四态、来源字段、人工修正和开放集", "未确认结果进入正式状态")),
        (New-Row @("FR-04", "关系投影", "确认/补偿/撤权后的重建与溯源", "图谱成为第二事实源或泄露字段")),
        (New-Row @("FR-05", "规则与预算", "规则单测、严重案例、去重、预算和证据卡", "严重漏报或被预算压制")),
        (New-Row @("FR-06", "计划闭环", "时间窗、版本差异、确认/延期/跳过和授权升级", "系统修改剂量/药物或升级给无权对象")),
        (New-Row @("FR-07", "环境行动卡", "出口请求、事件去重和天气故障", "上传健康详情或进入用药链")),
        (New-Row @("FR-08", "证据助手", "同一盲测集、引用、无证据、越权、提示注入和医疗拒答", "引用伪造、危险建议或云端外发")),
        (New-Row @("FR-09", "大屏/实验室", "聚合脱敏、版本指标、发布和回滚", "敏感正文进入公共展示或指标")),
        (New-Row @("FR-10", "困难样本 V2", "训练授权、数据卡、固定集 V1/V2、失败样例和回滚", "未授权训练、固定集泄漏或不可回滚"))
    )
    Add-Paragraph $Document "状态只允许使用未开始、进行中、待验收、已验证、阻塞和不做。状态变化必须有 Issue/Story、提交或 PR、自动测试、人工验收、环境/版本和回滚证据；CI 通过不能单独证明业务完成。"

    Add-Heading $Document "附录" 1
    Add-Heading $Document "参考资料" 2
    Add-Table $Document @("编号", "资料名称", "版本/日期", "用途") @(
        (New-Row @("R-01", "HomeCare Twin 项目说明", "2026-08-10 当前仓库", "产品定位、技术基线和实际状态入口")),
        (New-Row @("R-02", "HomeCare Twin 需求规格说明", "P0 需求基线", "FR-01 至 FR-10、NFR-01 至 NFR-07")),
        (New-Row @("R-03", "产品信息架构与页面设计", "P0 设计基线", "十页结构、状态矩阵和文案边界")),
        (New-Row @("R-04", "技术方案与系统架构", "P0 方案基线", "总体架构、模块职责和降级策略")),
        (New-Row @("R-05", "API 设计规范与当前 OpenAPI", "2026-08-10", "接口、权限、幂等、状态机和错误契约")),
        (New-Row @("R-06", "领域模型、Alembic 0001–0007", "2026-08-10", "物理数据结构、约束和迁移状态")),
        (New-Row @("R-07", "数据与隐私安全规范、威胁基线", "P0 安全基线", "数据分级、授权、网络出口、留存和事件响应")),
        (New-Row @("R-08", "AI 与 RAG 设计规范", "P0 AI 基线", "OCR-first、RAG、模型校验和红队边界")),
        (New-Row @("R-09", "测试与验收方案", "P0 验收基线", "指标、E2E、发布阻断和证据要求")),
        (New-Row @("R-10", "需求追踪矩阵与 HCT Stories", "截至 2026-08-08 的状态入口", "区分需求、实现和验收状态")),
        (New-Row @("R-11", "ADR-0002/0003/0004/0005", "2026-08-03 至 2026-08-08", "可信域、Owner 权限、资源档位和事件恢复决策"))
    )

    Add-Heading $Document "需求编号索引" 2
    Add-Paragraph $Document "功能需求：FR-01 身份家庭与授权；FR-02 健康事件中心；FR-03 多证据视觉；FR-04 关系投影；FR-05 风险规则与预算；FR-06 计划与照护升级；FR-07 环境行动卡；FR-08 本地证据助手；FR-09 大屏与模型实验室；FR-10 困难样本与追加训练。"
    Add-Paragraph $Document "非功能需求：NFR-01 安全；NFR-02 隐私；NFR-03 可追溯；NFR-04 降级可用；NFR-05 性能；NFR-06 可复现；NFR-07 可访问与可理解。"
}

function Add-DesignBody {
    param($Document)

    Add-Heading $Document "研发背景" 1
    Add-Paragraph $Document "家健镜 HomeCare Twin 的设计对象是一个本地优先、事件驱动、证据可验证的家庭居家照护教学演示系统。设计以家庭事实为中心，把身份与授权、健康事件、视觉证据、关系投影、确定性规则、照护计划、本地知识检索和模型解释放在一条可回放、可审计的数据链上。"
    Add-Paragraph $Document "设计不把模型猜测写成健康事实，不把关系投影或向量索引设为第二事实源，也不让语言模型拥有风险等级、处方或剂量决定权。家庭版默认拒绝网络出口，基础档在模型或向量依赖不可用时仍能维护事实、授权、事件、规则和任务。"
    Add-Note $Document "设计状态：P0 V1.0 设计基线。本文同时记录目标架构、当前已存在的物理结构和未决兼容点；当前代码存在不等同于完成全部 P0 业务验收。"

    Add-Heading $Document "阅读对象" 1
    Add-Table $Document @("读者", "需要从本文获得的内容") @(
        (New-Row @("项目负责人/产品负责人", "边界、范围、验收、风险、版本单元和回滚决策")),
        (New-Row @("后端开发与数据库维护", "模块依赖、事务边界、接口、数据表、迁移、事件恢复和安全约束")),
        (New-Row @("前端开发", "页面状态、API 入口、字段可见范围、错误/降级和可访问性要求")),
        (New-Row @("视觉/数据/模型负责人", "OCR-first 管线、证据契约、数据划分、模型登记、固定集和发布门禁")),
        (New-Row @("测试/安全/运维人员", "风险场景、测试分层、网络出口、备份、恢复、删除和事件响应")),
        (New-Row @("课程评审与答辩人员", "连续演示链、非目标、已验证/未验证边界和可定位证据"))
    )

    Add-Heading $Document "参考资料" 1
    Add-Table $Document @("编号", "资料名称", "版本/日期", "采用内容") @(
        (New-Row @("D-01", "HomeCare Twin README", "2026-08-10 当前仓库", "产品承诺、技术栈、P0 路线和当前状态")),
        (New-Row @("D-02", "需求规格说明书 P0 基线", "FR-01 至 FR-10 / NFR-01 至 NFR-07", "设计输入、非目标和验收边界")),
        (New-Row @("D-03", "系统架构与模块边界", "P0 架构基线", "模块责任、依赖方向、数据所有权")),
        (New-Row @("D-04", "技术方案与部署运维方案", "P0 方案基线", "MySQL、FastAPI、视觉、RAG、Ollama 和三档部署")),
        (New-Row @("D-05", "API 设计规范与当前 OpenAPI", "2026-08-10", "接口、状态机、错误、幂等、证据契约")),
        (New-Row @("D-06", "领域模型与 Alembic 0001–0007", "2026-08-10", "逻辑表、物理字段、迁移和事件恢复")),
        (New-Row @("D-07", "数据与隐私安全、威胁模型", "P0 安全基线", "数据分级、授权、网络、删除和响应")),
        (New-Row @("D-08", "AI 与 RAG 设计规范", "P0 AI 基线", "多证据、检索前授权、输出校验和拒答")),
        (New-Row @("D-09", "测试与验收方案", "P0 验收基线", "质量目标、E2E、发布阻断和证据包")),
        (New-Row @("D-10", "ADR-0002/0003/0004/0005", "2026-08-03 至 2026-08-08", "可信域、Owner、资源档位、事件恢复")),
        (New-Row @("D-11", "当前源代码、迁移和测试", "当前分支 HEAD", "实际接口、表结构和可执行实现边界"))
    )

    Add-Heading $Document "术语、缩略语" 1
    Add-Table $Document @("术语", "说明") @(
        (New-Row @("API", "FastAPI 统一业务入口，路径前缀为 /api/v1；前端不得直连数据库、向量库或 Ollama。")),
        (New-Row @("ABAC", "基于属性的访问控制；本项目属性包括家庭、成员、字段、动作、目的、期限和撤权状态。")),
        (New-Row @("ADR", "记录架构决策、备选方案、影响、验收、复审和回滚。")),
        (New-Row @("CV/OCR", "计算机视觉/光学字符识别；P0 采用全图 OCR 主链路。")),
        (New-Row @("E2E", "端到端测试，从录入到确认、事件、风险、任务和删除/降级的连续场景。")),
        (New-Row @("health_event", "追加写家庭健康事实变化，具有成员内序号、确认状态、证据和版本。")),
        (New-Row @("outbox", "与事实事件同事务写入的最小异步派发记录。")),
        (New-Row @("projection", "由事件归约生成的查询状态或关系投影，可重建。")),
        (New-Row @("checkpoint", "带序号、事件 ID、状态 JSON 和 SHA-256 的投影重放检查点。")),
        (New-Row @("RAG", "权限前置过滤的本地检索增强生成；检索片段只作为可引用证据。")),
        (New-Row @("LLM", "本地大语言模型；负责路由、工具选择、澄清和语言解释，不负责事实和风险决策。")),
        (New-Row @("P0/P1", "课程优先交付范围/后续增强范围。")),
        (New-Row @("MATCHED/CONFLICT/UNKNOWN/REVIEW", "对外视觉识别结果状态；REVIEW 表示质量或证据不足。")),
        (New-Row @("LOW_QUALITY", "当前 review_task 物理枚举中的低质量融合状态；与需求层 REVIEW 的对应关系尚未通过契约决策。")),
        (New-Row @("版本单元", "代码、迁移、视觉/OCR、主数据、规则、知识/Embedding、模型/LoRA、提示词和 Schema 的可发布组合。"))
    )

    Add-Heading $Document "详细设计" 1
    Add-Heading $Document "设计目标与原则" 2
    Add-Table $Document @("原则", "设计规定", "验证方式") @(
        (New-Row @("事实分层", "MySQL 保存事实；图谱和向量为派生物；模型预测必须经人工确认。", "数据所有权审查、投影重建测试")),
        (New-Row @("事件追加", "健康状态变化追加 health_event；补偿关联原事件；不原地更新/删除。", "触发器、补偿、重放和审计测试")),
        (New-Row @("证据优先", "视觉、风险和助手输出携带来源、确认状态和版本；证据不足即停。", "字段来源、引用存在、拒答固定集")),
        (New-Row @("本地可信域", "API、数据库、文件、视觉/OCR、向量和 Ollama 默认在家庭可信域；出口默认拒绝。", "出口阻断、天气 payload、依赖离线演练")),
        (New-Row @("最小授权", "Owner/非 Owner 分开判定，非 Owner 细化到成员、字段、动作、目的、期限和升级。", "跨家庭、字段、撤权和过期测试")),
        (New-Row @("分档降级", "基础档不依赖向量/LLM；增强档再启用本地检索和模型；研发档与家庭运行分离。", "三档 Compose、依赖故障和恢复演练")),
        (New-Row @("可回滚", "每个发布组合登记版本/哈希；模型、规则、知识、迁移和应用均有回滚或前滚路径。", "备份恢复、固定集、组合版本检查"))
    )

    Add-Heading $Document "系统上下文与信任边界" 2
    Add-Flow $Document "受信任家庭局域网/机构内网`n┌──────────────────────────────────────────────────────────────┐`n│ 浏览器 → Nginx/HTTPS → Vue Web → FastAPI /api/v1              │`n│                                    ├→ 身份/授权/审计          │`n│                                    ├→ 事件/投影/outbox/规则  │`n│                                    ├→ 本地文件与版本登记      │`n│                                    └→ CV/OCR/RAG/Ollama 适配器│`n│              MySQL 是唯一事实主库；图谱/向量为可重建派生物   │`n└──────────────────────────────────────────────────────────────┘`n默认拒绝网络出口 → 仅允许天气适配器（城市/区县编码）`n不允许健康正文、图片、视频、向量、对话和模型上下文自动离开可信域"
    Add-Paragraph $Document "信任边界由 FastAPI 统一执行。前端、管理员端、视觉模块、RAG 和 Ollama 都不能绕过应用服务写入业务表；异步任务只传引用、序号、确认状态和版本，不在 outbox 或日志复制健康 payload。"

    Add-Heading $Document "部署视图与三档运行" 2
    Add-Table $Document @("部署档位", "必选组件", "可选组件", "故障行为", "资源准入") @(
        (New-Row @("基础档", "Nginx、Vue、FastAPI、MySQL、outbox worker、规则、轻量 OCR、加密文件", "无", "模型/向量/天气不可用不影响事实、授权、规则和任务", "4 逻辑核、8 GiB RAM、20 GiB 磁盘为暂定最低")),
        (New-Row @("增强档", "基础档全部", "FAISS/Qdrant、Ollama 量化模型", "RAG/LLM 失败退化为事实/规则卡；不云端回退", "建议 16 GiB RAM，7B Q4 建议 8 GiB 可用显存")),
        (New-Row @("研发档", "增强档全部", "标注、训练、评测、模型登记和制品存储", "训练失败保留实验，不影响家庭运行", "独立训练设备、授权数据和版本化制品"))
    )
    Add-Paragraph $Document "部署入口由 scripts/start.ps1 或 scripts/start.sh 提供 setup、up、health、down、check。API 镜像启动时前滚到 Alembic head；worker 在 API 健康后启动并回收过期锁；down 默认保留数据库卷。"

    Add-Heading $Document "分层与模块边界" 2
    Add-Flow $Document "Web/Admin → routes（协议、依赖、Schema） → application（授权、事务、用例、编排） → domain（事件状态机、规则、时间窗） → persistence/integration interfaces`nadapters → MySQL/文件/CV/OCR/RAG/Ollama/天气"
    Add-Table $Document @("模块", "负责", "不负责", "主要依赖") @(
        (New-Row @("Web", "十页业务页面、状态、证据和授权展示", "鉴权决策、SQL、模型调用、事实写入", "/api/v1")),
        (New-Row @("routes", "HTTP、认证依赖、Schema、状态码和 request_id", "SQL、规则计算和模型推理", "application services")),
        (New-Row @("application", "授权上下文、事务、事件追加、复核、工具编排", "框架级页面布局和数据库细节", "domain + repository/integration interfaces")),
        (New-Row @("domain", "事件状态机、幂等、投影归约、规则、时间窗和预算", "FastAPI、ORM、外部服务", "纯数据和接口")),
        (New-Row @("persistence", "SQLAlchemy/MySQL 访问、迁移、投影和审计", "绕过授权的业务决策", "MySQL 8")),
        (New-Row @("vision", "预处理、OCR、条码、YOLO 辅助、候选和版本", "创建正式健康事实", "本地文件、模型和主数据")),
        (New-Row @("review", "候选确认/修正/跳过及事件事务", "重写原始预测", "vision task + health event")),
        (New-Row @("rules", "确定风险等级、去重和预算", "诊断、处方和 LLM 自由决策", "已确认投影和规则版本")),
        (New-Row @("RAG/LLM", "权限后检索、工具选择、引用和语言解释", "直读全库、改事实、改风险或用药决定", "本地 FAISS/Qdrant/Ollama")),
        (New-Row @("egress/weather", "默认拒绝出口和城市编码天气适配", "传输健康上下文", "白名单目的地")),
        (New-Row @("admin/model", "规则/知识/模型登记、固定集、发布/回滚", "因管理员身份读取家庭正文", "版本仓库和脱敏指标"))
    )

    Add-Heading $Document "模块界面" 2
    Add-Heading $Document "Web 与统一 API" 3
    Add-Table $Document @("接口契约", "设计") @(
        (New-Row @("前缀", "所有业务接口使用 /api/v1；健康检查 /health 保持独立。")),
        (New-Row @("格式", "JSON snake_case；时间为含时区 ISO 8601；公开 ID 使用 UUID/ULID。")),
        (New-Row @("请求追踪", "X-Request-ID 由客户端提供时校验格式，否则由服务端生成；响应回传同一 ID。")),
        (New-Row @("幂等", "写操作接受 Idempotency-Key；事件、视觉任务、人工复核和授权更新分别执行各自幂等/版本约束。")),
        (New-Row @("授权", "认证只证明身份；每次家庭/成员资源访问仍执行 Owner/非 Owner 和字段级 ABAC。")),
        (New-Row @("错误", "当前 P0 实现兼容 FastAPI {detail}；目标统一 error.code/message/details/request_id，前端必须兼容迁移期两种格式。")),
        (New-Row @("可观测", "日志含 request_id、对象 ID、动作、版本、稳定错误码和计数，不含敏感正文。"))
    )

    Add-Heading $Document "身份、授权与审计模块" 3
    Add-Flow $Document "session → actor_id → household boundary → Owner or valid authorization → field/action/purpose/expiry → filtered response + access_audit"
    Add-Paragraph $Document "授权记录字段包括 grantor_actor_id、grantee_actor_id、household/member、data_fields、actions、purpose、valid_from、valid_until、revoked_at、version 和更新时间。更新/撤权使用 expected_version，冲突不覆盖；access_audit 记录授权 ID、操作者、动作、字段、目的、允许/拒绝、原因和前后版本，不保存健康正文。"

    Add-Heading $Document "文件与视觉任务模块" 3
    Add-Flow $Document "UploadFile → extension/MIME/magic/size/content check → random storage_key + digest → vision_task(queued) → local worker → result/version/error → review_task(PENDING_REVIEW)"
    Add-Paragraph $Document "当前物理实现以 file_id/storage_key 引用文件，vision_task 保存输入摘要、预处理/模型/阈值/Schema/代码/数据版本、结果和时间。正式视觉管线应在此接口上接入全图 OCR、条码、YOLO 辅助和候选融合，并保持原始证据不可被结构化模型覆盖。"

    Add-Heading $Document "人工复核与事件事务模块" 3
    Add-Flow $Document "review_task PENDING_REVIEW → CONFIRMED / CORRECTED / SKIPPED`nCONFIRMED/CORRECTED → health_event + outbox + projection（同一事务）`nSKIPPED → review_task 状态与原因，不生成正式健康事件"
    Add-Paragraph $Document "复核任务的确认与修正使用状态守卫，非 PENDING_REVIEW 返回冲突；确认保存 selected_candidate，修正保存 manual_payload 和原 candidates。复核事件必须带 MANUAL_REVIEW 来源和确认状态。"
    Add-Note $Document "兼容性未决：需求层状态为 REVIEW，当前 review_task 的 FusionStatus 枚举为 MATCHED、CONFLICT、UNKNOWN、LOW_QUALITY。发布前必须由 API/OpenAPI、迁移、前端状态和契约测试决定是否映射为 REVIEW，未决前不得在数据中混用。"

    Add-Heading $Document "事件、outbox 与投影模块" 3
    Add-Flow $Document "normalize key → canonical request fingerprint → lock member → next sequence → append immutable event → create minimal outbox → reduce projection → commit`nworker → claim PENDING/FAILED → PROCESSING → apply in sequence → DISPATCHED or stable FAILED"
    Add-Paragraph $Document "health_event 的 payload/evidence 保留在事实库并最小化；outbox payload 只含 event/household/member ID、sequence、confirmation 和 Schema 版本。在线投影保存 state、last_event_id、last_sequence、version 和 state_hash；checkpoint 保存可重建状态和哈希。"

    Add-Heading $Document "关系投影模块" 3
    Add-Table $Document @("投影对象", "来源", "可见条件", "重建规则") @(
        (New-Row @("成员—疾病", "已确认 condition 事件", "成员字段授权", "按成员序号归约，补偿事件覆盖当前语义但不删除历史")),
        (New-Row @("成员—过敏", "已确认 allergy 事件", "过敏字段授权", "未确认/撤销状态不得进入正式边")),
        (New-Row @("成员—药品—成分", "人工确认药品和本地主数据", "药品/计划字段授权", "候选、UNKNOWN、CONFLICT、REVIEW 不建正式节点")),
        (New-Row @("药品—批次—计划", "库存批次和计划事件", "计划/任务授权", "计划按版本和批准状态重建")),
        (New-Row @("照护关系", "授权记录与成员关系", "授权/审计权限", "撤权立即从可见投影隐藏"))
    )

    Add-Heading $Document "规则、计划和天气模块" 3
    Add-Paragraph $Document "规则模块接收已确认成员状态和 versioned ruleset，返回 Alert(rule_id、level、message、source_event_ids、created_at)，之后按去重键和预算合并。当前代码已经存在过期、低库存、重复成分、过敏和有限 interaction 函数；完整规则集、来源、版本和发布证据仍需后续 Story。"
    Add-Paragraph $Document "计划模块提供 confirm/defer/skip 和安全时间窗校验；天气模块只接收城市/区县编码，使用 egress_guard 校验出口 payload。天气不进入药物更改链路。"

    Add-Heading $Document "RAG、LLM 与安全校验模块" 3
    Add-Flow $Document "intent/safety route → permission filter → SQL/graph/rule/RAG tools → evidence bundle → local model → JSON Schema → citation access → claim fidelity → medical/no-commerce/urgent checks → response or refusal"
    Add-Table $Document @("校验顺序", "失败行为") @(
        (New-Row @("Schema", "返回结构化错误或降级卡，不自由重试扩大权限")),
        (New-Row @("工具绑定", "确认 facts/rules/citations 与真实工具调用一致")),
        (New-Row @("引用可访问", "任何引用不在当前成员/字段授权内即拒绝回答")),
        (New-Row @("事实忠实", "主张超出事实、规则或文档范围即澄清/拒答")),
        (New-Row @("规则不可改写", "模型文字不能改变等级、预算和规则版本")),
        (New-Row @("医疗禁止", "诊断、处方、停药、换药、剂量请求转受控拒答或紧急升级")),
        (New-Row @("无导流", "买药、问诊、广告、佣金和健康消费词命中即阻断"))
    )

    Add-Heading $Document "模型与数据治理模块" 3
    Add-Flow $Document "授权/脱敏 → 数据卡 → 按实体/日期/设备/会话分组 → 标注复核 → 固定集哈希 → 训练/评测 → 模型卡 → 批准/拒绝 → 家庭端发布或回滚"
    Add-Paragraph $Document "产品使用同意和训练同意必须分开。模型登记至少保存基础模型许可证、训练数据版本、参数、提交、硬件、随机种子、指标、失败样例、阈值、量化/导出哈希、适用/禁止用途、批准人和回滚版本。"

    Add-Heading $Document "模块内处理流程" 2
    Add-Heading $Document "访问决策算法" 3
    Add-Flow $Document "authenticated? → family match? → actor is owner? → if non-owner: member match ∧ field match ∧ action match ∧ purpose match ∧ valid_from≤now<valid_until ∧ revoked_at=null → allow + audit"
    Add-Paragraph $Document "Owner 的管理权限来自 household.created_by，不因显示角色名称推断。非 Owner 的 purpose 使用稳定 ASCII 代码；跨家庭/ID 猜测对外统一 404。任何拒绝都不能通过前端隐藏代替 API 过滤。"

    Add-Heading $Document "视觉候选融合算法" 3
    Add-Flow $Document "candidate_score = 0.40 × OCR 文本一致度 + 0.30 × 条码一致度 + 0.15 × 包装类型一致度 + 0.15 × 规格/厂家主数据一致度"
    Add-Paragraph $Document "该分数只对已有主数据候选排序，不生成新的药品身份。阈值必须在固定评估集上校准并登记版本；条码与药名冲突、关键字段缺失、候选差距过小、未知 SKU 或质量不足分别进入 CONFLICT、UNKNOWN 或 REVIEW。字段值必须引用 OCR token/区域或条码来源。"

    Add-Heading $Document "事件幂等与状态投影算法" 3
    Add-Numbered $Document 1 "规范化操作、操作者和 payload，生成 request_fingerprint。"
    Add-Numbered $Document 2 "在家庭范围查询 Idempotency-Key；相同指纹返回原事件，不同指纹返回 IDEMPOTENCY_KEY_CONFLICT。"
    Add-Numbered $Document 3 "锁定成员行并分配单调 sequence_no；唯一索引阻止重复序号。"
    Add-Numbered $Document 4 "健康事件、最小 outbox 和在线投影在同一事务提交；事务失败全部回滚。"
    Add-Numbered $Document 5 "worker 只按已确认前序派发；缺失前序返回 OUT_OF_ORDER，重复投递通过 last_sequence 去重。"
    Add-Numbered $Document 6 "重放前检查 checkpoint 家庭/成员、序号和 SHA-256，完成后与在线 state_hash 比较。"

    Add-Heading $Document "风险去重与预算算法" 3
    Add-Flow $Document "rule alerts → severity normalize → dedup_key(member, rule, window) → merge INFO/GENERAL under budget → pass HIGH/URGENT independently → evidence card"
    Add-Paragraph $Document "普通预算只影响通知表达和合并，不删除原始风险事实；免打扰也不等于删除。任何 HIGH/URGENT 不得因预算为零而静默。规则输出必须带 rule_id、version、source_event_ids、覆盖范围和有效期。"

    Add-Heading $Document "安全时间窗算法" 3
    Add-Paragraph $Document "计划服务先读取只读医嘱事实和当前计划版本，校验当前时间是否在安全时间窗内，再生成提醒策略变更建议。确认、延期和跳过均追加可审计事件；超出时间窗或缺少有效批准时拒绝优化。连续未确认达到阈值后，先查询可处理提醒且授权未撤回的照护者，再生成升级任务。"

    Add-Heading $Document "RAG 与回答校验算法" 3
    Add-Numbered $Document 1 "识别当前用户、家庭、成员和访问目的。"
    Add-Numbered $Document 2 "在检索前过滤文档权限、成员字段、版本和失效时间。"
    Add-Numbered $Document 3 "分别调用 SQL、图谱、规则和文档工具，并记录工具调用版本。"
    Add-Numbered $Document 4 "构造证据契约，确保每个主张可定位到已确认事实、规则或文档片段。"
    Add-Numbered $Document 5 "执行 Schema、引用可访问性、忠实性、规则不可改写、医疗禁止和无导流检查。"
    Add-Numbered $Document 6 "失败返回澄清、拒答、紧急升级或结构化降级，不让模型自行扩大权限。"

    Add-Heading $Document "删除传播算法" 3
    Add-Flow $Document "delete/revoke request → scope + purpose + second confirmation → revoke API/cache/notification immediately → delete/anonymize MySQL → remove files → rebuild/remove vectors → clear cache → mark backup disposition → minimal audit"
    Add-Paragraph $Document "审计只保留操作者、时间、请求 ID、范围、结果等最小合法证明，不保留健康正文。删除任务返回任务 ID并可查询各存储层处置状态。"

    Add-Heading $Document "模块类图" 2
    Add-Caption $Document "图 1 领域对象与服务关系（文本化类图）"
    Add-Flow $Document "Household 1──* Member 1──* HealthEvent`nHousehold 1──* CareAuthorization ──* AccessAudit`nHealthEvent 1──1 OutboxMessage ──> MemberStateProjection ──> RelationshipGraph`nVisionTask 1──* ReviewTask ──> HealthEvent`nReviewTask ──> HardSample（需独立训练同意）`nMember ──* MedicationPlan ──* ReminderEvent ──> RiskAlert`nKnowledgeDocument ──* KnowledgeChunk ──> CitationRecord ──> AssistantResponse"
    Add-Table $Document @("类/对象", "关键属性", "责任", "来源/写入者") @(
        (New-Row @("Household", "id/name/created_by/created_at", "家庭边界和 Owner 事实", "API/MySQL")),
        (New-Row @("Member", "household_id/display_name/role/actor_id", "家庭成员和身份关联", "API/MySQL")),
        (New-Row @("CareAuthorization", "grantor/grantee/member/fields/actions/purpose/validity/version", "非 Owner 最小访问授权", "Owner/API")),
        (New-Row @("HealthEvent", "sequence/source/status/payload/evidence/correlation/causation", "不可变健康事实变化", "应用服务/人工确认")),
        (New-Row @("OutboxMessage", "event/status/attempts/lock/error", "可靠派发引用", "事务 outbox/worker")),
        (New-Row @("MemberStateProjection", "state/last_sequence/version/state_hash", "可查询当前状态", "投影器")),
        (New-Row @("VisionTask", "file/status/digest/versions/result", "异步视觉任务生命周期", "视觉任务服务")),
        (New-Row @("ReviewTask", "fusion/candidates/status/manual_payload", "人工确认/修正状态", "复核服务")),
        (New-Row @("RiskAlert", "rule/level/source_event_ids/budget", "规则结果和证据入口", "确定性规则")),
        (New-Row @("AssistantResponse", "route/facts/rules/citations/visibility/versions", "受校验语言解释", "FastAPI 校验器"))
    )

    Add-Heading $Document "数据流" 2
    Add-Caption $Document "图 2 主链数据流"
    Add-Flow $Document "D3 原始媒体 → 文件校验/加密引用 → VisionTask → OCR/条码/YOLO 证据 → ReviewTask → 人工确认 → D2 HealthEvent`nD2 HealthEvent → Outbox（最小引用）→ Projection/Rule → RiskEvidence/Reminder`nD2 事实 + D0/D1 知识 → 权限前置 RAG → 本地 LLM → Citation/AssistantResponse`n撤权/删除 → API、文件、索引、缓存、通知、可控备份处置；AccessAudit 只留最小证明"
    Add-Table $Document @("数据流", "输入", "处理", "输出", "敏感性/控制") @(
        (New-Row @("视觉录入", "D3 图片/视频文件引用", "质量门控、OCR、条码、包装、主数据融合", "四态候选和版本", "本地；未知/冲突不得入正式状态")),
        (New-Row @("事件写入", "人工确认或手工事实", "幂等、序号、事务、outbox、投影", "健康事件和状态哈希", "D2；追加写、加密、审计")),
        (New-Row @("规则计算", "已确认状态", "规则版本、去重、预算", "风险卡和任务", "D2；LLM 不参与等级决定")),
        (New-Row @("证据回答", "获权事实/规则/文档", "工具调用、RAG、Schema和引用校验", "回答/拒答/结构化降级", "不出网；逐字段授权")),
        (New-Row @("数据删除", "撤权/删除任务", "传播到各派生层和备份处置", "任务状态和最小审计", "不保留健康正文"))
    )

    Add-Heading $Document "外部接口" 2
    Add-Heading $Document "当前 OpenAPI 接口分组" 3
    Add-Paragraph $Document "以下路径来自当前分支 FastAPI OpenAPI 输出。它们是代码接口清单，不代表每项已完成完整 P0 业务验收；完整状态仍以需求追踪矩阵、Story、测试和人工证据为准。"
    Add-Table $Document @("分组", "方法", "路径", "用途/约束") @(
        (New-Row @("健康与元数据", "GET", "/health", "服务健康检查")),
        (New-Row @("健康与元数据", "GET", "/api/v1/health/db", "数据库 SELECT 1 健康检查")),
        (New-Row @("健康与元数据", "GET", "/api/v1/meta/capabilities", "返回 P0-foundation 当前 available/unavailable 能力")),
        (New-Row @("认证", "POST", "/api/v1/auth/register", "本地账号注册；P0 骨架")),
        (New-Row @("认证", "POST", "/api/v1/auth/login", "密码登录并建立会话")),
        (New-Row @("认证", "POST", "/api/v1/auth/logout", "注销会话")),
        (New-Row @("认证", "POST", "/api/v1/auth/pin-challenge", "生成高敏操作二次确认挑战")),
        (New-Row @("认证", "POST", "/api/v1/auth/pin-verify", "验证 PIN 二次确认")),
        (New-Row @("家庭", "GET", "/api/v1/households", "列出当前用户可见家庭")),
        (New-Row @("家庭", "POST", "/api/v1/households", "创建家庭并形成 Owner")),
        (New-Row @("成员", "GET", "/api/v1/households/{household_id}/members", "按家庭边界列出成员")),
        (New-Row @("成员", "POST", "/api/v1/households/{household_id}/members", "添加成员")),
        (New-Row @("授权", "GET", "/api/v1/households/{household_id}/authorizations", "Owner 查询授权")),
        (New-Row @("授权", "POST", "/api/v1/households/{household_id}/authorizations", "创建字段/动作/目的/期限授权")),
        (New-Row @("授权", "PATCH", "/api/v1/households/{household_id}/authorizations/{authorization_id}", "expected_version 更新授权")),
        (New-Row @("授权", "POST", "/api/v1/households/{household_id}/authorizations/{authorization_id}/revoke", "expected_version 撤回授权")),
        (New-Row @("授权审计", "GET", "/api/v1/households/{household_id}/authorization-audits", "Owner 查询脱敏授权/访问审计")),
        (New-Row @("事件", "POST", "/api/v1/households/{household_id}/events", "追加 MANUAL 健康事件，支持幂等")),
        (New-Row @("事件", "GET", "/api/v1/households/{household_id}/events", "按家庭/成员查询事件")),
        (New-Row @("事件", "POST", "/api/v1/households/{household_id}/events/{event_id}/compensations", "追加补偿事件")),
        (New-Row @("状态", "GET", "/api/v1/households/{household_id}/members/{member_id}/state", "查询成员状态投影")),
        (New-Row @("状态", "POST", "/api/v1/households/{household_id}/members/{member_id}/state/checkpoints", "创建 checkpoint")),
        (New-Row @("状态", "POST", "/api/v1/households/{household_id}/members/{member_id}/state/replay", "Owner 从空状态/checkpoint 重放")),
        (New-Row @("状态", "POST", "/api/v1/households/{household_id}/members/{member_id}/projection/rebuild", "触发成员投影重建")),
        (New-Row @("时间线", "GET", "/api/v1/households/{household_id}/members/{member_id}/timeline", "事件和证据时间线")),
        (New-Row @("outbox", "GET", "/api/v1/households/{household_id}/outbox", "Owner 查询派发恢复状态")),
        (New-Row @("outbox", "POST", "/api/v1/households/{household_id}/outbox/dispatch", "Owner 手工触发恢复批次")),
        (New-Row @("文件", "POST", "/api/v1/files/upload", "白名单文件上传和本地引用")),
        (New-Row @("文件", "GET", "/api/v1/files/{storage_key}", "按随机存储键读取文件")),
        (New-Row @("文件", "DELETE", "/api/v1/files/{storage_key}", "删除文件树并返回处置结果")),
        (New-Row @("视觉", "POST", "/api/v1/vision-tasks", "创建异步视觉任务")),
        (New-Row @("视觉", "GET", "/api/v1/vision-tasks/{task_id}", "查询视觉任务状态/版本/结果")),
        (New-Row @("视觉", "GET", "/api/v1/households/{household_id}/vision-tasks", "列出家庭视觉任务")),
        (New-Row @("视觉", "POST", "/api/v1/vision-tasks/{task_id}/cancel", "取消视觉任务")),
        (New-Row @("复核", "GET", "/api/v1/households/{household_id}/members/{member_id}/review-tasks", "列出待复核任务")),
        (New-Row @("复核", "GET", "/api/v1/households/{household_id}/review-tasks/{task_id}", "读取候选和证据状态")),
        (New-Row @("复核", "POST", "/api/v1/households/{household_id}/review-tasks/{task_id}/confirm", "确认候选并同事务生成事件")),
        (New-Row @("复核", "POST", "/api/v1/households/{household_id}/review-tasks/{task_id}/correct", "修正候选并同事务生成事件")),
        (New-Row @("复核", "POST", "/api/v1/households/{household_id}/review-tasks/{task_id}/skip", "跳过复核，不生成正式事件")),
        (New-Row @("规则", "POST", "/api/v1/households/{household_id}/rules/run", "按当前状态运行规则")),
        (New-Row @("风险", "GET", "/api/v1/households/{household_id}/members/{member_id}/risks", "列出风险与等级")),
        (New-Row @("风险", "GET", "/api/v1/households/{household_id}/members/{member_id}/risks/{rule_id}", "查看风险及来源事件")),
        (New-Row @("计划", "POST", "/api/v1/households/{household_id}/members/{member_id}/plans/confirm", "确认计划动作")),
        (New-Row @("计划", "POST", "/api/v1/households/{household_id}/members/{member_id}/plans/defer", "延期并记录原因")),
        (New-Row @("计划", "POST", "/api/v1/households/{household_id}/members/{member_id}/plans/skip", "跳过并记录原因")),
        (New-Row @("环境", "GET", "/api/v1/weather/action-cards", "仅通过白名单城市编码生成环境卡"))
    )

    Add-Heading $Document "目标扩展接口" 3
    Add-Table $Document @("方法", "路径", "目标", "门禁") @(
        (New-Row @("POST", "/vision/jobs/image|video", "按输入类型创建识别任务", "本地文件、状态机、版本")),
        (New-Row @("GET", "/vision/jobs/{id}", "返回完整候选和证据", "字段来源、四态和授权")),
        (New-Row @("POST", "/recognitions/{id}/review", "统一确认/纠正/拒绝", "人工状态和事件事务")),
        (New-Row @("GET", "/members/{id}/visibility", "查看当前调用者可见范围", "同一授权事实")),
        (New-Row @("POST", "/risks/evaluate", "按规则版本重算风险", "已确认事实和证据")),
        (New-Row @("POST", "/plans/{id}/optimize|approve", "提醒策略建议与批准", "安全时间窗、医嘱只读")),
        (New-Row @("POST", "/assistant/chat", "本地证据助手", "权限前置、引用、拒答和无导流")),
        (New-Row @("POST", "/models/retrain", "研发环境追加训练", "训练同意、固定集、模型卡、回滚")),
        (New-Row @("GET", "/dashboard/family|model", "家庭/模型大屏", "聚合脱敏、管理员权限")),
        (New-Row @("DELETE", "/members/{id}/data", "数据删除传播任务", "二次确认、处置任务、最小审计"))
    )

    Add-Heading $Document "接口错误与状态" 3
    Add-Table $Document @("类别", "当前/目标行为") @(
        (New-Row @("认证", "UNAUTHENTICATED；会话无效或缺失")),
        (New-Row @("资源隐藏", "跨家庭、未授权和 ID 猜测统一 RESOURCE_NOT_FOUND/404")),
        (New-Row @("授权", "FORBIDDEN_MEMBER、CONSENT_REVOKED、AUTHORIZATION_VERSION_CONFLICT")),
        (New-Row @("请求", "VALIDATION_ERROR、FILE_REJECTED、RATE_LIMITED")),
        (New-Row @("事件", "IDEMPOTENCY_KEY_CONFLICT、EVENT_ALREADY_SUPERSEDED、OUT_OF_ORDER、CHECKPOINT_INVALID")),
        (New-Row @("证据/模型", "EVIDENCE_CONFLICT、EVIDENCE_INSUFFICIENT、MODEL_UNAVAILABLE、RULE_VERSION_MISMATCH")),
        (New-Row @("迁移期格式", "P0 现有实现使用 {detail}；P1 目标为 error.code/message/details/request_id，调用方必须兼容。"))
    )

    Add-Heading $Document "数据库设计" 1
    Add-Heading $Document "数据库设计综述" 2
    Add-Paragraph $Document "MySQL 8 是唯一业务事实主库，使用 SQLAlchemy 2 和 Alembic 管理访问与迁移。关系图是 MySQL 派生投影；FAISS/Qdrant 只存可重建向量和权限元数据引用；本地文件由随机存储键和数据库引用关联；模型登记只描述制品，不成为家庭健康事实。"
    Add-Table $Document @("数据域", "逻辑对象", "当前物理实现", "事实/派生属性") @(
        (New-Row @("家庭权限", "family/user/member/care_relation/consent/access_audit", "household/member/care_authorization/access_audit；本地 auth 仍为骨架", "household/member/authorization 是事实；审计是追加证明")),
        (New-Row @("健康事件", "condition/allergy/metric/document/health_event", "health_event + member_state_projection + projection_checkpoint", "事件是事实；状态是派生")),
        (New-Row @("药品计划", "medicine/ingredient/batch/member_medicine/plan/reminder", "当前由事件 payload、规则和计划服务承载，完整主数据表待后续迁移", "药品主数据和计划目标需版本化")),
        (New-Row @("视觉复核", "recognition_task/evidence/human_review/hard_sample", "vision_task/review_task；证据暂保存在 JSON result/candidates", "原始媒体是 D3，复核结论经确认后才是事实")),
        (New-Row @("规则风险", "rule/risk/risk_evidence/environment", "规则函数和 API 响应；持久化完整风险模型待后续 Story", "规则等级不是模型输出")),
        (New-Row @("知识助手", "knowledge_document/chunk/chat/tool/citation/model", "完整 RAG/LLM 表和索引待后续 Story", "知识与模型版本必须可追踪"))
    )
    Add-Paragraph $Document "当前迁移链为 0001_initial_schema、0002_allow_pending_health_events、0003_hct102_authorization_security、0004_hct103_event_idempotency、0005_hct103_event_recovery、0006_hct207_review_task、0007_hct204_vision_task。实际发布前仍需按空库、已有数据、索引/外键、失败恢复、前滚和回滚策略执行迁移验收。"

    Add-Heading $Document "数据库逻辑结构设计" 2
    Add-Flow $Document "Household → Member → HealthEvent → OutboxMessage → MemberStateProjection/Checkpoint`nHousehold → CareAuthorization → AccessAudit`nVisionTask → ReviewTask → HealthEvent`nHealthEvent/Projection → RuleEvaluation/RiskEvidence → Reminder/Plan`nKnowledgeDocument → KnowledgeChunk → CitationRecord → AssistantResponse"
    Add-Table $Document @("逻辑关系", "基数/约束", "一致性要求") @(
        (New-Row @("家庭—成员", "1:N；member.household_id 必须存在", "所有成员资源检查 household_id")),
        (New-Row @("成员—事件", "1:N；成员内 sequence_no 单调且唯一", "事件追加写；投影按序")),
        (New-Row @("事件—outbox", "1:1；event_id 唯一", "同一事务创建；outbox 不含健康正文")),
        (New-Row @("成员—投影", "1:1；member_id 主键", "last_sequence/state_hash 可校验")),
        (New-Row @("授权—审计", "1:N；审计不因业务级联删除", "保留最小证明")),
        (New-Row @("视觉—复核", "1:N；复核状态守卫", "只有确认/修正触发正式事件")),
        (New-Row @("事件—风险", "1:N 证据引用", "规则版本和来源事件完整"))
    )

    Add-Heading $Document "数据库物理结构设计" 2
    Add-Paragraph $Document "下表以当前 ORM 和 0001–0007 迁移为物理结构依据；计划域、完整风险证据域、知识/RAG 域列为后续设计对象，不冒充已存在表。JSON 字段用于保存受控结构，必须限制大小、脱敏并通过 Schema 校验。"
    Add-Table $Document @("表", "主键/索引", "关键列与约束", "用途") @(
        (New-Row @("household", "id；created_by 索引", "name VARCHAR(120) NOT NULL；created_by VARCHAR(120) NOT NULL；created_at", "家庭边界和 Owner 事实")),
        (New-Row @("member", "id；household_id/actor_id 索引", "household_id FK；display_name；role SELF/DEPENDENT/CAREGIVER；actor_id 可空；created_at", "家庭成员目录")),
        (New-Row @("care_authorization", "id；household_id/member_id/grantor/grantee 索引", "data_fields JSON；actions JSON；purpose；valid_from/until；revoked_at；version；created/updated_at", "非 Owner 字段/动作/目的/期限授权")),
        (New-Row @("access_audit", "id；household_id/time、authorization_id 索引", "actor/operation/action/data_field/purpose/outcome/reason/before_version/after_version/created_at", "追加写最小授权和访问证明")),
        (New-Row @("health_event", "id；household/member/sequence 唯一；household/idempotency 唯一；supersedes 唯一", "event_type/source/confirmation_status/payload/evidence/created_by/confirmed_by/idempotency_key/request_fingerprint/correlation_id/causation_id/compensates_event_id/supersedes_event_id/schema_version/occurred_at/created_at", "不可变健康事实事件")),
        (New-Row @("outbox_message", "id；event_id 唯一；status/available_at 索引", "topic/payload/dispatched/status/attempts/available_at/locked_at/dispatched_at/last_error/created_at/updated_at", "事务 outbox 最小派发记录")),
        (New-Row @("member_state_projection", "member_id 主键；household/member", "state JSON；last_event_id；last_sequence；version；state_hash；updated_at", "在线当前状态")),
        (New-Row @("projection_checkpoint", "id；member_id/last_sequence 唯一", "household/member/last_sequence/last_event_id/state JSON/state_hash/created_by/created_at", "重放 checkpoint")),
        (New-Row @("vision_task", "id；household/member/file/status/index；idempotency_key 全局唯一", "task_type/status/error_code/error_message/input_digest/preprocess_version/model_version/model_threshold/schema_version/code_version/data_version/result/started_at/finished_at/created_by/created_at/updated_at", "异步视觉任务生命周期")),
        (New-Row @("review_task", "id；vision/household/member/status/fusion 索引；幂等键唯一", "status：PENDING_REVIEW/CONFIRMED/CORRECTED/SKIPPED；fusion：MATCHED/CONFLICT/UNKNOWN/LOW_QUALITY；候选、确认/修正、操作者、版本和时间", "人工复核与事件事务"))
    ) -ColumnWidths @(62, 98, 225, 65)

    Add-Heading $Document "数据库安全设计" 2
    Add-Table $Document @("控制", "设计") @(
        (New-Row @("访问层", "应用服务统一执行家庭边界和 ABAC；数据库连接不暴露公网；前端/模型/索引不直连业务表。")),
        (New-Row @("加密", "传输使用 HTTPS/内网加密；数据库、文件、备份和密钥分离；D3 原图使用独立密钥与最短留存。")),
        (New-Row @("事件不可变", "SQLite/MySQL 迁移建立拒绝 UPDATE/DELETE 的触发器；已有事件时不执行破坏性 downgrade。")),
        (New-Row @("审计保留", "access_audit 不保存健康正文，已有审计记录时禁止通过降级迁移删除历史。")),
        (New-Row @("备份", "加密覆盖 MySQL、必要文件、规则/知识清单和模型登记；投影/向量可重建；定期演练恢复并记录 RPO/RTO。")),
        (New-Row @("删除", "任务传播到主库、文件、索引、缓存和可控备份；审计仅保留最小合法证明。")),
        (New-Row @("日志", "worker 和 API 只记录批次、计数、稳定错误码和 request_id，不输出 event payload、evidence、成员状态或异常正文。"))
    )

    Add-Heading $Document "数据字典" 2
    Add-Heading $Document "household、member 与授权" 3
    Add-Table $Document @("表/字段", "类型", "约束", "含义") @(
        (New-Row @("household.id", "VARCHAR(36)", "PK，UUID", "家庭公开内部标识")),
        (New-Row @("household.name", "VARCHAR(120)", "NOT NULL", "家庭显示名称，不承载健康正文")),
        (New-Row @("household.created_by", "VARCHAR(120)", "NOT NULL，索引", "当前 Owner actor_id")),
        (New-Row @("household.created_at", "DATETIME", "默认当前时间", "创建时间")),
        (New-Row @("member.id", "VARCHAR(36)", "PK，UUID", "成员标识")),
        (New-Row @("member.household_id", "VARCHAR(36)", "FK，NOT NULL", "所属家庭")),
        (New-Row @("member.display_name", "VARCHAR(120)", "NOT NULL", "成员展示名")),
        (New-Row @("member.role", "VARCHAR(32)", "SELF/DEPENDENT/CAREGIVER", "显示角色，不能单独决定权限")),
        (New-Row @("member.actor_id", "VARCHAR(120)", "可空，索引", "与本地操作者关联")),
        (New-Row @("care_authorization.data_fields", "JSON array", "至少 1 项", "授权字段路径，如 health_events")),
        (New-Row @("care_authorization.actions", "JSON array", "READ_EVENTS/WRITE_EVENTS", "允许动作")),
        (New-Row @("care_authorization.purpose", "VARCHAR(200)", "ASCII 代码校验", "使用目的")),
        (New-Row @("care_authorization.valid_from/until", "DATETIME", "时间窗口", "授权开始/到期")),
        (New-Row @("care_authorization.revoked_at", "DATETIME", "可空", "撤权时间；非空立即失效")),
        (New-Row @("care_authorization.version", "INTEGER", "≥1，CAS", "乐观锁版本")),
        (New-Row @("access_audit.outcome", "VARCHAR(16)", "ALLOW/DENY", "访问决定")),
        (New-Row @("access_audit.reason", "VARCHAR(64)", "可空稳定代码", "拒绝/允许原因")),
        (New-Row @("access_audit.before/after_version", "INTEGER", "可空", "授权变更前后版本"))
    )

    Add-Heading $Document "health_event、outbox 与投影" 3
    Add-Table $Document @("字段", "类型", "约束", "含义") @(
        (New-Row @("health_event.id", "VARCHAR(36)", "PK", "事件 ID")),
        (New-Row @("household_id/member_id", "VARCHAR(36)", "FK，NOT NULL", "家庭和成员边界")),
        (New-Row @("sequence_no", "INTEGER", "成员内唯一递增", "事件顺序")),
        (New-Row @("event_type/source", "VARCHAR(80/40)", "NOT NULL", "事件类别和来源")),
        (New-Row @("confirmation_status", "VARCHAR(32)", "CONFIRMED/UNCONFIRMED", "是否可进入正式投影")),
        (New-Row @("payload/evidence", "JSON", "NOT NULL", "最小事实变化和证据引用")),
        (New-Row @("created_by/confirmed_by", "VARCHAR(120)", "confirmed_by 可空", "创建者和确认者")),
        (New-Row @("idempotency_key", "VARCHAR(128)", "家庭内唯一语义", "请求重试幂等键")),
        (New-Row @("request_fingerprint", "VARCHAR(64)", "哈希", "操作/操作者/payload 指纹")),
        (New-Row @("correlation_id/causation_id", "VARCHAR(120/36)", "causation 可空", "业务链和因果关联")),
        (New-Row @("compensates_event_id/supersedes_event_id", "VARCHAR(36)", "补偿/覆盖关系", "历史更正关联")),
        (New-Row @("schema_version", "INTEGER", "默认 1", "事件结构版本")),
        (New-Row @("occurred_at/created_at", "DATETIME", "含时区语义", "发生时间和记录时间")),
        (New-Row @("outbox.status", "VARCHAR(16)", "PENDING/PROCESSING/FAILED/DISPATCHED", "派发状态")),
        (New-Row @("outbox.attempts", "INTEGER", "≥0", "重试次数")),
        (New-Row @("outbox.available_at/locked_at/dispatched_at", "DATETIME", "可空按状态", "可取、锁定和完成时间")),
        (New-Row @("outbox.last_error", "VARCHAR(64)", "稳定代码，不含正文", "最近失败原因")),
        (New-Row @("projection.state", "JSON", "NOT NULL", "当前可查询状态")),
        (New-Row @("projection.last_sequence/version", "INTEGER", "非负", "最后事件序号和投影版本")),
        (New-Row @("projection.state_hash", "VARCHAR(64)", "SHA-256", "状态完整性哈希")),
        (New-Row @("checkpoint.state_hash", "VARCHAR(64)", "NOT NULL", "重放前校验哈希"))
    )

    Add-Heading $Document "vision_task 与 review_task" 3
    Add-Table $Document @("字段", "类型", "约束/状态", "含义") @(
        (New-Row @("vision_task.file_id", "VARCHAR(120)", "NOT NULL，索引", "本地文件引用")),
        (New-Row @("vision_task.task_type/status", "VARCHAR(40/32)", "状态由状态机保护", "OCR/条码任务及 queued/running/succeeded/failed/timeout/cancelled")),
        (New-Row @("vision_task.idempotency_key", "VARCHAR(128)", "当前物理全局唯一", "任务创建幂等键")),
        (New-Row @("vision_task.input_digest", "VARCHAR(64)", "哈希", "输入完整性引用")),
        (New-Row @("vision_task.preprocess/model/schema/code/data_version", "VARCHAR(64)", "可空", "参与任务的版本单元")),
        (New-Row @("vision_task.model_threshold", "FLOAT", "0–1", "候选/模型阈值")),
        (New-Row @("vision_task.result", "JSON", "可空", "任务结果；须脱敏和 Schema 校验")),
        (New-Row @("review_task.status", "ENUM", "PENDING_REVIEW/CONFIRMED/CORRECTED/SKIPPED", "复核生命周期")),
        (New-Row @("review_task.fusion_status", "ENUM", "MATCHED/CONFLICT/UNKNOWN/LOW_QUALITY", "当前物理融合状态")),
        (New-Row @("review_task.candidates", "JSON", "NOT NULL", "候选列表和证据摘要")),
        (New-Row @("review_task.selected_candidate/manual_payload", "JSON", "可空", "确认选择或人工修正")),
        (New-Row @("review_task.idempotency_key", "VARCHAR(128)", "当前物理全局唯一", "复核操作幂等键")),
        (New-Row @("review_task.confirmed_by/confirmed_at", "VARCHAR/DATETIME", "可空", "确认者和时间")),
        (New-Row @("review_task.model_version/rule_version", "VARCHAR(64)", "可空", "候选/规则版本"))
    )

    Add-Heading $Document "计划、规则、知识与未来表" 3
    Add-Table $Document @("逻辑表", "建议关键字段", "发布前要求") @(
        (New-Row @("medicine/medicine_ingredient", "medicine_id、名称、规格、厂家、成分、来源、版本", "本地主数据、许可和版本化")),
        (New-Row @("medicine_batch", "批次、有效期、库存、来源事件", "只接受已确认药品，库存变更有事件")),
        (New-Row @("medication_plan", "药品、医嘱版本、剂量/频次只读事实、提醒策略、时间窗", "医嘱事实与策略分离；批准可审计")),
        (New-Row @("risk_event/risk_evidence", "等级、规则版本、去重键、有效期、FACT/RULE/DOCUMENT/CONFIRMATION 引用", "严重案例零漏报；证据完整")),
        (New-Row @("knowledge_document/chunk", "来源、许可、版本、哈希、权限域、页码/章节、Embedding 版本", "检索前权限过滤；知识不可覆盖系统规则")),
        (New-Row @("chat/tool/citation", "route、request、工具参数/结果、引用、模型/知识版本", "不写健康正文到日志；引用可访问")),
        (New-Row @("model_version/hard_sample", "数据卡、模型哈希、指标、失败样例、训练同意、批准/回滚", "同一固定集 V1/V2；家庭端不训练"))
    )

    Add-Heading $Document "系统可靠性设计" 1
    Add-Heading $Document "故障隔离与降级" 2
    Add-Table $Document @("依赖故障", "隔离点", "用户可见行为", "恢复动作") @(
        (New-Row @("MySQL", "API/事务层", "请求 ID + 受控错误；不写半成品", "备份恢复或前滚迁移")),
        (New-Row @("outbox worker", "派发层", "事件事实和在线状态仍可查；显示待派发", "回收过期锁、重试批次、检查序号")),
        (New-Row @("视觉/OCR", "vision adapter", "任务失败/待重试，允许手工录入", "重新运行同版本任务或人工复核")),
        (New-Row @("向量库", "RAG adapter", "禁用自然语言证据回答", "重建索引并校验权限/版本")),
        (New-Row @("Ollama", "LLM adapter", "显示事实、规则、引用和 MODEL_UNAVAILABLE", "恢复本地模型，重新跑 Schema/安全回归")),
        (New-Row @("天气", "egress/weather adapter", "不更新行动卡，不影响本地任务", "白名单目的、超时和缓存期恢复")),
        (New-Row @("投影", "projection service", "显示重建中，不沿用过期敏感缓存", "事件重放并比较 state_hash"))
    )

    Add-Heading $Document "并发、幂等与一致性" 2
    Add-Bullet $Document "成员行锁和成员内 sequence_no 唯一约束共同保证事件顺序。"
    Add-Bullet $Document "Idempotency-Key 关联家庭、操作、操作者和规范 payload；同键不同指纹返回 409。"
    Add-Bullet $Document "授权更新/撤回用 expected_version；计划和状态更新使用版本/ETag，避免静默覆盖。"
    Add-Bullet $Document "复核状态由 PENDING_REVIEW 守卫；重复确认、修正或跳过返回 409，避免重复事件。"
    Add-Bullet $Document "outbox 事件唯一；重复投递由 last_sequence 去重；缺少已确认前序保持 OUT_OF_ORDER。"

    Add-Heading $Document "备份、恢复与回滚" 2
    Add-Table $Document @("对象", "备份/登记", "恢复/回滚") @(
        (New-Row @("MySQL 事实库", "加密备份、迁移 head、字符集/时区", "先恢复事实，再以前滚迁移；有事件时禁止破坏性 downgrade")),
        (New-Row @("文件", "加密文件和存储键清单", "按删除/留存任务恢复或处置；不把原图放日志")),
        (New-Row @("投影/向量", "版本、哈希和重建参数", "从事件/文档重建，不反向覆盖事实")),
        (New-Row @("规则/知识", "来源、许可、版本、哈希、有效期", "回退上一批准版本并重新验证引用/规则")),
        (New-Row @("视觉/LLM 模型", "权重外置、模型卡、导出哈希、量化和回滚版本", "家庭端只拉取批准制品；失败回到基础档")),
        (New-Row @("应用/API", "Git SHA、依赖锁、镜像摘要、迁移组合", "停止 worker，切换兼容应用或前滚修复"))
    )

    Add-Heading $Document "性能、监控与容量" 2
    Add-Table $Document @("指标域", "观测项", "敏感数据控制") @(
        (New-Row @("技术", "请求量/延迟/错误、数据库连接、CPU/GPU/RAM/磁盘、模型加载和推理延迟", "只记录不可逆聚合、版本和 request_id")),
        (New-Row @("事件链", "outbox 状态/尝试/过期锁、投影 last_sequence 和 state_hash", "不记录 event payload")),
        (New-Row @("业务", "识别状态、复核时长、风险等级、告警合并、任务确认和升级", "不包含家庭姓名、病史或报告正文")),
        (New-Row @("模型", "模型/阈值、字段准确率、未知转人工率、工具/引用失败和漂移", "使用固定集或匿名聚合")),
        (New-Row @("隐私", "出口目的、授权依据、响应状态、删除传播任务", "不记录健康详情、完整提示词和密钥"))
    )

    Add-Heading $Document "安全设计与威胁缓解" 2
    Add-Table $Document @("威胁", "影响", "控制与证据") @(
        (New-Row @("跨家庭/成员越权", "泄露敏感健康数据", "家庭边界、Owner/非 Owner、字段 ABAC、隐藏式 404、授权测试")),
        (New-Row @("撤权后缓存可见", "已撤回同意仍被访问", "每次读取实时校验；清理缓存/索引/通知；撤权 E2E")),
        (New-Row @("恶意文件/路径穿越", "执行、覆盖或读取系统文件", "扩展/MIME/magic、大小、随机键、内容检查、上传安全测试")),
        (New-Row @("提示词注入/恶意文档", "改变安全规则或泄露上下文", "文档提示词视为数据；系统规则不可被检索内容覆盖；红队测试")),
        (New-Row @("模型幻觉/危险建议", "错误医疗判断", "证据契约、Schema、引用和医疗禁止词校验；无证据拒答")),
        (New-Row @("健康数据出网", "隐私和合规风险", "默认拒绝出口、天气白名单 payload、云端不作默认回退、网络测试")),
        (New-Row @("训练数据投毒/泄露", "模型质量和隐私风险", "授权/脱敏审核、分组切分、固定集哈希、模型卡和回滚")),
        (New-Row @("日志泄露", "健康正文或密钥暴露", "log_mask、最小审计、worker 稳定错误码、secret scan"))
    )

    Add-Heading $Document "附录" 1
    Add-Heading $Document "当前实现与设计差异清单" 2
    Add-Table $Document @("差异点", "当前实现/证据", "设计处理", "发布前动作") @(
        (New-Row @("需求 REVIEW 与物理 LOW_QUALITY", "需求/API 使用 REVIEW；review.py 与 0006 使用 LOW_QUALITY", "不擅自宣称等价，保留双层状态说明", "统一 OpenAPI、迁移、前端和契约测试")),
        (New-Row @("P0 error 格式", "当前 FastAPI 默认 {detail}", "文档同时给出现状和目标 error.code 契约", "迁移期兼容测试，P1 冻结统一格式")),
        (New-Row @("视觉业务质量", "当前有 vision_task/review_task 接口和迁移", "不把任务接口写成模型质量已达标", "授权数据、固定集、模型卡、指标和失败样例")),
        (New-Row @("RAG/LLM/天气", "capabilities 返回 unavailable", "设计完整链路并明确结构化降级", "后续 Story 实现本地依赖、引用和安全回归")),
        (New-Row @("计划/规则持久化", "当前部分逻辑由服务函数和事件承载", "逻辑模型先行，物理表标为后续迁移", "完成规则/计划版本登记和删除传播")),
        (New-Row @("完整十页 Web", "当前 Web 目录有骨架和局部视图测试", "设计写全十页状态，不声明完整 UI 已交付", "逐页 E2E、可访问性和离线验收")),
        (New-Row @("追踪状态日期", "矩阵截至 2026-08-08，当前分支有 2026-08-10 合并", "以可定位证据和维护者状态为准", "合并新能力后同步矩阵、Story 和评审记录"))
    )

    Add-Heading $Document "设计验收清单" 2
    Add-Bullet $Document "模块边界：路由不写 SQL，前端不直连数据库/向量/Ollama，LLM 不承载确定性规则。"
    Add-Bullet $Document "状态边界：未确认、UNKNOWN、CONFLICT、REVIEW/LOW_QUALITY 不参与正式状态和风险计算。"
    Add-Bullet $Document "一致性：事件、outbox、在线投影、checkpoint、补偿和恢复具有可定位测试。"
    Add-Bullet $Document "授权：Owner 与非 Owner 的规则清楚，字段/动作/目的/期限/撤权经过 API 测试。"
    Add-Bullet $Document "证据：风险卡和助手回答可展开事实、规则、文档、确认和版本；无证据拒答。"
    Add-Bullet $Document "隐私：默认拒绝出口、天气粗粒度、日志脱敏、删除传播和备份处置有证据。"
    Add-Bullet $Document "发布：代码、迁移、数据/模型/规则/知识/提示词组合登记，固定集、E2E、部署恢复和回滚齐全。"

    Add-Heading $Document "版本组合登记模板" 2
    Add-Table $Document @("组成项", "本次基线记录") @(
        (New-Row @("代码提交", "以提交 SHA 和 PR/merge 记录为准")),
        (New-Row @("数据库迁移", "Alembic 0001–0007；HCT-103 有事件时前滚修复")),
        (New-Row @("视觉/OCR/阈值", "当前任务元数据可记录；正式版本待固定集验收")),
        (New-Row @("主数据/规则", "规则 v0/逻辑函数已有起步；正式规则登记待后续 Story")),
        (New-Row @("知识/Embedding", "当前 unavailable；增强档启用前必须登记来源、权限和哈希")),
        (New-Row @("LLM/LoRA/量化", "Ollama 本地资源原型已验证；业务模型和 QLoRA 对照待交付")),
        (New-Row @("提示词/Schema", "输出 Schema 和安全校验为目标契约，发布前需固定版本")),
        (New-Row @("回滚", "保留上一稳定组合；模型/规则/知识独立回滚，迁移使用兼容应用或前滚"))
    )
}

function Finalize-Document {
    param($Document)
    try { [void]$Document.Fields.Update() } catch { }
    try {
        if ($Document.TablesOfContents.Count -gt 0) {
            [void]$Document.TablesOfContents.Item(1).Update()
        }
    } catch { }
    [void]$Document.Repaginate()
    $pages = $Document.ComputeStatistics($wdStatisticPages)
    $cover = $Document.Tables.Item(1)
    Set-CellText -Table $cover -Row 3 -Column 2 -Text ("Total pages 共 " + $pages + " 页")
    [void]$Document.Fields.Update()
    [void]$Document.Repaginate()
    $pages = $Document.ComputeStatistics($wdStatisticPages)
    Set-CellText -Table $cover -Row 3 -Column 2 -Text ("Total pages 共 " + $pages + " 页")
    [void]$Document.Repaginate()
    return [int]$pages
}

function New-DeliveryDocument {
    param(
        $Word,
        [string]$TemplatePath,
        [string]$OutputPath,
        [ValidateSet("requirements", "design")] [string]$Kind
    )
    if (Test-Path -LiteralPath $OutputPath) {
        Remove-Item -LiteralPath $OutputPath -Force
    }
    $document = $Word.Documents.Add($TemplatePath, $false, 0, $false)
    try {
        Configure-DocumentStyles -Document $document
        Set-FrontMatter -Document $document -Kind $Kind
        Reset-TemplateBody -Document $document
        if ($Kind -eq "requirements") {
            Add-RequirementsBody -Document $document
        } else {
            Add-DesignBody -Document $document
        }
        $pages = Finalize-Document -Document $document
        $document.SaveAs2($OutputPath, $wdFormatDocumentDefault)
        return [pscustomobject]@{ Path = $OutputPath; Pages = $pages }
    } finally {
        $document.Close($wdDoNotSaveChanges)
        [void][Runtime.InteropServices.Marshal]::ReleaseComObject($document)
    }
}

$repoRoot = Split-Path -Parent $PSScriptRoot
$templateRoot = Join-Path $repoRoot "doc\09.文档模板"
$requirementsOutput = Join-Path $repoRoot "doc\01.需求说明书\家健镜 HomeCare Twin 需求规格说明书-P0-V1.0.docx"
$designOutput = Join-Path $repoRoot "doc\02.设计说明书\家健镜 HomeCare Twin 软件设计说明书-P0-V1.0.docx"

$word = New-Object -ComObject Word.Application
$word.Visible = $false
$word.DisplayAlerts = 0
$word.AutomationSecurity = 3
try {
    if ($DocumentKind -in @("all", "requirements")) {
        $rawResult = New-DeliveryDocument -Word $word -TemplatePath (Join-Path $templateRoot "需求规格说明书_模板-v2.0.dotm") -OutputPath $requirementsOutput -Kind requirements
        $result = @($rawResult)[-1]
        Write-Output ("REQUIREMENTS|" + $result.Path + "|pages=" + $result.Pages)
    }
    if ($DocumentKind -in @("all", "design")) {
        $rawResult = New-DeliveryDocument -Word $word -TemplatePath (Join-Path $templateRoot "设计说明书_模板-v1.3.dotm") -OutputPath $designOutput -Kind design
        $result = @($rawResult)[-1]
        Write-Output ("DESIGN|" + $result.Path + "|pages=" + $result.Pages)
    }
} finally {
    $word.Quit()
    [void][Runtime.InteropServices.Marshal]::ReleaseComObject($word)
    [GC]::Collect()
    [GC]::WaitForPendingFinalizers()
}
