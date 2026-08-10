<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'

import { ApiClientError, apiClient } from './api/client'
import type { CapabilityResponse, HealthResponse } from './api/types'

type DesignId =
  | 'forest'
  | 'night'
  | 'paper'
  | 'solar'
  | 'cobalt'
  | 'mono'
  | 'tide'
  | 'ember'
  | 'mist'
  | 'signal'

type PreviewView = 'dashboard' | 'evidence' | 'pages'

interface DesignOption {
  id: DesignId
  name: string
  label: string
  description: string
  cue: string
  bestFor: string
  palette: [string, string, string]
}

const designs: DesignOption[] = [
  {
    id: 'forest',
    name: '森系可信域',
    label: 'Calm Care',
    description: '低刺激、亲和、让隐私与确认感自然出现。',
    cue: '温和但不软弱',
    bestFor: '家庭日常',
    palette: ['#b9e0cd', '#3e816d', '#f4c970'],
  },
  {
    id: 'night',
    name: '夜航监护台',
    label: 'Night Watch',
    description: '深色高对比，适合全天候查看任务与升级。',
    cue: '安静的值守感',
    bestFor: '照护大屏',
    palette: ['#213c4c', '#65d7bf', '#ffbd70'],
  },
  {
    id: 'paper',
    name: '纸上档案',
    label: 'Care Journal',
    description: '像一本有证据链的家庭照护记录册。',
    cue: '编辑部式可信度',
    bestFor: '档案与时间线',
    palette: ['#e9d9bf', '#9d5139', '#203d39'],
  },
  {
    id: 'solar',
    name: '日光提醒',
    label: 'Sunlit Routine',
    description: '暖色和大圆角把任务变成可理解的日常节奏。',
    cue: '轻快、可亲、好记',
    bestFor: '家庭成员',
    palette: ['#f5c75f', '#e47455', '#3c7565'],
  },
  {
    id: 'cobalt',
    name: '蓝图协作',
    label: 'Blueprint Ops',
    description: '冷静的蓝紫系统感，突出状态、版本和责任人。',
    cue: '像产品蓝图一样清楚',
    bestFor: '运营工作台',
    palette: ['#c3c9ff', '#5c55e8', '#e88fc9'],
  },
  {
    id: 'mono',
    name: '黑白临床档案',
    label: 'Monochrome Record',
    description: '去掉装饰，把事实、状态与动作放到最前面。',
    cue: '极简、直接、可审计',
    bestFor: '管理端',
    palette: ['#e8e8e3', '#111111', '#b9b9b2'],
  },
  {
    id: 'tide',
    name: '海风蓝图',
    label: 'Tide & Trust',
    description: '清透蓝色和波纹层次，传达本地运行的稳定感。',
    cue: '清爽、宽松、可靠',
    bestFor: '家庭总览',
    palette: ['#b9e6ef', '#2889a3', '#f0b46d'],
  },
  {
    id: 'ember',
    name: '琥珀调度',
    label: 'Amber Dispatch',
    description: '暖橙作为行动信号，强调风险等级而不是制造焦虑。',
    cue: '有行动力的温暖',
    bestFor: '风险与计划',
    palette: ['#4a302a', '#ff9f62', '#ffe3a6'],
  },
  {
    id: 'mist',
    name: '轻雾照护',
    label: 'Soft Signal',
    description: '柔和紫雾与层叠卡片，适合解释型 AI 与证据阅读。',
    cue: '耐心、轻盈、留白多',
    bestFor: '本地助手',
    palette: ['#ddd6fa', '#7b67cb', '#efb5c5'],
  },
  {
    id: 'signal',
    name: '信号仪表',
    label: 'Signal Grid',
    description: '模块化网格把事件、状态、版本和降级路径排列清楚。',
    cue: '信息密度与秩序',
    bestFor: '模型实验室',
    palette: ['#d9f2df', '#2a8f62', '#e85b55'],
  },
]

const pages = [
  ['P0-01', '家庭总览', '变化、待确认风险、今日任务与隐私状态', '⌂'],
  ['P0-02', '成员健康档案', '只展示当前操作者获权的事实、来源与时间线', '◉'],
  ['P0-03', '视觉扫描中心', '质量门控、多渠道证据与四态候选展示', '▣'],
  ['P0-04', '人工复核中心', '对照原证据，确认、修正或拒绝识别结果', '↺'],
  ['P0-05', '家庭健康图谱', '由已确认事件重建成员、药品与照护关系', '⌘'],
  ['P0-06', '用药安全中心', '规则等级、证据、版本与处理状态', '△'],
  ['P0-07', '健康计划中心', '区分医嘱事实与安全时间窗内的提醒策略', '◷'],
  ['P0-08', '本地健康助手', '先展示事实、规则和文档，再给出受限解释', '✦'],
  ['P0-09', '家庭健康大屏', '只显示非敏感聚合、任务与本地运行状态', '◫'],
  ['P0-10', '模型实验室', '固定集指标、版本、发布与回滚状态', '⌁'],
] as const

const selectedId = ref<DesignId>('forest')
const activeView = ref<PreviewView>('dashboard')
const selectedTask = ref(0)
const apiState = ref<'checking' | 'connected' | 'offline'>('checking')
const apiVersion = ref('')
const capability = ref<CapabilityResponse | null>(null)
const toast = ref('')

const selectedDesign = computed(
  () => designs.find((design) => design.id === selectedId.value) ?? designs[0],
)

const rootClasses = computed(() => [
  'app-root',
  `theme-${selectedDesign.value.id}`,
  `layout-${selectedDesign.value.id}`,
])

const apiLabel = computed(() => {
  if (apiState.value === 'checking') return '正在检查服务'
  if (apiState.value === 'connected') return `API 在线${apiVersion.value ? ` · v${apiVersion.value}` : ''}`
  return 'API 离线 · 保留原型预览'
})

const availableCount = computed(() => capability.value?.available.length ?? 0)

function swatchStyle(design: DesignOption): Record<string, string> {
  return {
    '--swatch-a': design.palette[0],
    '--swatch-b': design.palette[1],
    '--swatch-c': design.palette[2],
  }
}

function showToast(message: string) {
  toast.value = message
  window.setTimeout(() => {
    toast.value = ''
  }, 2400)
}

function selectDesign(id: DesignId) {
  selectedId.value = id
  activeView.value = 'dashboard'
  try {
    window.localStorage.setItem('homecare-twin-design', id)
  } catch {
    // Local preference is optional in the prototype.
  }
  const design = designs.find((item) => item.id === id)
  if (design) showToast(`已切换：${design.name}`)
}

function rememberDesign() {
  showToast(`已记下「${selectedDesign.value.name}」，可继续比较其他方向`)
}

async function loadServiceState() {
  try {
    const [health, capabilities] = await Promise.all([
      apiClient.getHealth(),
      apiClient.getCapabilities(),
    ])
    const response = health as HealthResponse
    apiVersion.value = response.version
    capability.value = capabilities
    apiState.value = 'connected'
  } catch (error) {
    if (error instanceof ApiClientError) {
      apiState.value = 'offline'
    } else {
      apiState.value = 'offline'
    }
  }
}

onMounted(() => {
  try {
    const stored = window.localStorage.getItem('homecare-twin-design') as DesignId | null
    if (stored && designs.some((design) => design.id === stored)) selectedId.value = stored
  } catch {
    // Local preference is optional in the prototype.
  }
  void loadServiceState()
})
</script>

<template>
  <div :class="rootClasses">
    <div class="ambient ambient-one" aria-hidden="true"></div>
    <div class="ambient ambient-two" aria-hidden="true"></div>

    <header class="site-header">
      <a class="brand" href="#top" aria-label="返回家健镜视觉方向评选顶部">
        <span class="brand-mark" aria-hidden="true"><i></i><i></i><i></i></span>
        <span class="brand-lockup">
          <strong>家健镜</strong>
          <small>HOMECARE TWIN · DESIGN BOARD</small>
        </span>
      </a>

      <nav class="primary-nav" aria-label="原型导航">
        <button
          class="nav-link"
          :class="{ active: activeView === 'dashboard' }"
          type="button"
          @click="activeView = 'dashboard'"
        >
          体验预览
        </button>
        <button
          class="nav-link"
          :class="{ active: activeView === 'pages' }"
          type="button"
          @click="activeView = 'pages'"
        >
          10 页信息架构
        </button>
        <button
          class="nav-link"
          :class="{ active: activeView === 'evidence' }"
          type="button"
          @click="activeView = 'evidence'"
        >
          证据链示例
        </button>
      </nav>

      <div class="header-status">
        <div class="privacy-chip"><span class="pulse-dot"></span> 本地可信域 · 默认不出网</div>
        <div class="api-chip" :class="`api-${apiState}`">
          <span class="api-dot"></span>{{ apiLabel }}<span v-if="apiState === 'connected'" class="api-count">{{ availableCount }} 项</span>
        </div>
      </div>
    </header>

    <main id="top">
      <section class="hero section-width">
        <div class="hero-copy">
          <span class="eyebrow">视觉方向评选 · 10 个候选方案</span>
          <h1>让每个变化，<em>都有证据</em>可追溯。</h1>
          <p class="hero-lede">
            家健镜是本地优先的家庭居家照护教学演示系统。这里把同一套 P0 信息架构做成十种视觉气质，方便团队先选方向，再进入真实 API 与状态实现。
          </p>
          <div class="hero-actions">
            <button class="button button-primary" type="button" @click="activeView = 'dashboard'">
              浏览当前方案 <span aria-hidden="true">↗</span>
            </button>
            <button class="button button-quiet" type="button" @click="rememberDesign">
              记下这套风格
            </button>
          </div>
          <div class="hero-footnote">
            <span class="footnote-mark">✓</span>
            <span>识别只是候选，确认后才进入健康记录。</span>
            <span class="footnote-divider"></span>
            <span>当前仅为 UI 视觉原型。</span>
          </div>
        </div>

        <div class="hero-art" aria-label="产品闭环示意">
          <div class="art-note art-note-top">P0 / CARE LOOP</div>
          <div class="art-board">
            <div class="art-board-head">
              <span class="art-window-dots"><i></i><i></i><i></i></span>
              <span>family_state / local</span>
              <span class="art-live">LIVE</span>
            </div>
            <div class="art-board-main">
              <div class="art-score">
                <span>已确认事件</span>
                <strong>12</strong>
                <small>↑ 2 条 / 本周</small>
              </div>
              <div class="art-wave" aria-hidden="true">
                <span></span><span></span><span></span><span></span><span></span><span></span><span></span><span></span>
              </div>
              <div class="art-list">
                <div><span class="mini-icon mini-green">✓</span><span>证据已确认</span><b>03</b></div>
                <div><span class="mini-icon mini-amber">!</span><span>等待人工复核</span><b>01</b></div>
                <div><span class="mini-icon mini-blue">↗</span><span>本地规则运行</span><b>OK</b></div>
              </div>
            </div>
          </div>
          <div class="art-sticker">NO<br />DIAGNOSIS</div>
          <div class="art-note art-note-bottom">facts → rules → care</div>
        </div>
      </section>

      <section class="style-section section-width" aria-labelledby="style-heading">
        <div class="section-heading">
          <div>
            <span class="section-number">01 / 视觉方向</span>
            <h2 id="style-heading">同一套业务，十种气质。</h2>
          </div>
          <p>点击任意卡片，预览相同家庭总览在不同视觉系统中的表现。</p>
        </div>

        <div class="style-grid">
          <button
            v-for="(design, index) in designs"
            :key="design.id"
            class="style-option"
            :class="{ selected: selectedId === design.id }"
            type="button"
            :aria-pressed="selectedId === design.id"
            @click="selectDesign(design.id)"
          >
            <span class="style-swatch" :style="swatchStyle(design)">
              <span class="swatch-number">{{ String(index + 1).padStart(2, '0') }}</span>
              <span class="swatch-light"></span>
              <span class="swatch-dark"></span>
            </span>
            <span class="style-option-copy">
              <span class="style-option-topline"><small>{{ design.label }}</small><span>{{ design.bestFor }}</span></span>
              <strong>{{ design.name }}</strong>
              <span>{{ design.description }}</span>
            </span>
            <span class="style-arrow" aria-hidden="true">↗</span>
          </button>
        </div>
      </section>

      <section class="preview-section section-width" aria-labelledby="preview-heading">
        <div class="section-heading preview-heading">
          <div>
            <span class="section-number">02 / 当前预览</span>
            <h2 id="preview-heading">{{ selectedDesign.name }}</h2>
          </div>
          <div class="preview-heading-side">
            <span class="selected-tag">已选方向</span>
            <span>{{ selectedDesign.cue }}</span>
          </div>
        </div>

        <div class="preview-tabs" role="tablist" aria-label="产品原型预览内容">
          <button class="preview-tab" :class="{ active: activeView === 'dashboard' }" type="button" @click="activeView = 'dashboard'">家庭总览</button>
          <button class="preview-tab" :class="{ active: activeView === 'evidence' }" type="button" @click="activeView = 'evidence'">多证据复核</button>
          <button class="preview-tab" :class="{ active: activeView === 'pages' }" type="button" @click="activeView = 'pages'">十页导航</button>
        </div>

        <div class="preview-window">
          <div class="preview-chrome">
            <span class="chrome-dots"><i></i><i></i><i></i></span>
            <span class="chrome-route">homecare-twin / {{ activeView === 'dashboard' ? 'family-overview' : activeView === 'evidence' ? 'evidence-review' : 'p0-information-architecture' }}</span>
            <span class="chrome-contract">P0 UI CONCEPT · SAMPLE DATA</span>
          </div>

          <div class="product-preview" :class="`preview-layout-${selectedDesign.id}`">
            <aside class="preview-sidebar">
              <div class="preview-brand"><span class="tiny-mark">✦</span><span>家健镜<small>LOCAL CARE</small></span></div>
              <div class="sidebar-label">家庭工作台</div>
              <button class="side-nav active" type="button" @click="activeView = 'dashboard'"><span>⌂</span>家庭总览<i>4</i></button>
              <button class="side-nav" type="button" @click="activeView = 'evidence'"><span>◌</span>待复核任务<i class="side-alert">1</i></button>
              <button class="side-nav" type="button" @click="activeView = 'pages'"><span>⌘</span>关系与事件</button>
              <button class="side-nav" type="button" @click="activeView = 'dashboard'"><span>◷</span>计划中心</button>
              <div class="sidebar-label sidebar-label-bottom">运行状态</div>
              <div class="sidebar-local"><span class="pulse-dot"></span><span><strong>本地模式</strong><small>健康数据默认不出网</small></span></div>
              <div class="sidebar-user"><span class="user-avatar">林</span><span><strong>林女士</strong><small>当前查看成员</small></span><span class="user-chevron">⌄</span></div>
            </aside>

            <div class="preview-content">
              <div class="preview-topline">
                <div>
                  <span class="preview-breadcrumb">家庭总览 <b>/</b> 周五 · 08.08</span>
                  <h3>{{ activeView === 'dashboard' ? '今天的照护，从确认开始。' : activeView === 'evidence' ? '每个结论，都能回到证据。' : '十个页面，串起一条照护闭环。' }}</h3>
                </div>
                <button class="member-switch" type="button"><span class="user-avatar">林</span><span>林女士</span><span class="user-chevron">⌄</span></button>
              </div>

              <div class="metric-row">
                <div class="metric-card metric-focus"><span>待确认事项</span><strong>04</strong><small>其中 1 条需要人工复核</small><i>↗</i></div>
                <div class="metric-card"><span>今日任务</span><strong>07</strong><small>已处理 3 / 7 项</small><i>◷</i></div>
                <div class="metric-card"><span>普通提醒预算</span><strong>2 <em>条</em></strong><small>严重事项不受预算压制</small><i>◎</i></div>
                <div class="metric-card"><span>本地服务</span><strong class="metric-ok">正常</strong><small>规则引擎 · 版本 R1.3</small><i>⌁</i></div>
              </div>

              <div v-if="activeView === 'dashboard'" class="dashboard-grid">
                <section class="preview-panel timeline-panel">
                  <div class="panel-title"><div><span class="panel-kicker">RECENT CHANGES</span><h4>最近发生了什么</h4></div><button type="button">查看全部 ↗</button></div>
                  <div class="timeline-list">
                    <div class="timeline-item"><span class="timeline-dot dot-green">✓</span><div><strong>手工事件已确认</strong><p>林女士 · 过敏史字段 · 08:42</p></div><span class="item-status status-confirmed">CONFIRMED</span></div>
                    <div class="timeline-item"><span class="timeline-dot dot-amber">!</span><div><strong>一条药品识别进入复核</strong><p>OCR 与包装主数据存在差异 · 08:17</p></div><span class="item-status status-review">REVIEW</span></div>
                    <div class="timeline-item"><span class="timeline-dot dot-blue">↗</span><div><strong>照护授权范围更新</strong><p>张先生 · 仅可查看用药摘要 · 昨日</p></div><span class="item-status status-audit">AUDIT</span></div>
                  </div>
                  <div class="timeline-footer"><span>事实来源 · 事件 / 授权 / 复核</span><span>本地记录</span></div>
                </section>

                <section class="preview-panel risk-panel">
                  <div class="panel-title"><div><span class="panel-kicker">NEEDS ATTENTION</span><h4>待确认风险</h4></div><span class="risk-count">2 项</span></div>
                  <button class="risk-card risk-high" type="button" @click="activeView = 'evidence'" @keydown.enter="activeView = 'evidence'">
                    <span class="risk-level"><i></i> HIGH</span><strong>识别结果需要人工复核</strong><p>不要让最高分候选自动进入正式记录。</p><span class="risk-action">查看证据 <b>↗</b></span>
                  </button>
                  <button class="risk-card risk-general" type="button"><span class="risk-level"><i></i> GENERAL</span><strong>普通提醒已合并</strong><p>今日合并 3 条，预算还剩 2 条。</p><span class="risk-action">查看摘要 <b>↗</b></span></button>
                  <div class="budget-bar"><span>告警预算</span><div><i></i><i></i><i class="empty"></i><i class="empty"></i><i class="empty"></i></div><b>2 / 5</b></div>
                </section>
              </div>

              <div v-else-if="activeView === 'evidence'" class="evidence-grid">
                <section class="preview-panel scan-panel">
                  <div class="panel-title"><div><span class="panel-kicker">ORIGINAL EVIDENCE</span><h4>原始影像 · 本地处理</h4></div><span class="frame-label">FRAME 03 / 08</span></div>
                  <div class="scan-canvas">
                    <div class="scan-grid-lines"></div>
                    <div class="fake-pack"><span>家庭常备</span><strong>药品<br />包装</strong><small>DEMO SAMPLE</small></div>
                    <span class="scan-box box-one"><b>包装区域</b></span><span class="scan-box box-two"><b>日期区域</b></span>
                    <span class="scan-corner corner-tl"></span><span class="scan-corner corner-br"></span>
                    <span class="scan-cross">+</span>
                  </div>
                  <div class="scan-meta"><span><i class="meta-dot green"></i>质量检查通过</span><span>本地帧提取 · 08:17</span></div>
                </section>
                <section class="preview-panel evidence-panel">
                  <div class="panel-title"><div><span class="panel-kicker">FUSED EVIDENCE</span><h4>多渠道证据</h4></div><span class="review-pill">REVIEW</span></div>
                  <div class="evidence-list">
                    <div class="evidence-row"><span class="evidence-icon">Y</span><div><strong>YOLO 包装检测</strong><small>包装区域 · 0.94 · V1.0</small></div><b class="evidence-pass">通过</b></div>
                    <div class="evidence-row"><span class="evidence-icon">O</span><div><strong>OCR 文字识别</strong><small>药品名字段 · 与主数据不一致</small></div><b class="evidence-warn">冲突</b></div>
                    <div class="evidence-row"><span class="evidence-icon">#</span><div><strong>条码 / 包装特征</strong><small>未读到条码 · 等待补拍</small></div><b class="evidence-warn">缺失</b></div>
                    <div class="evidence-row"><span class="evidence-icon">M</span><div><strong>本地主数据候选</strong><small>2 个候选 · 需要人工选择</small></div><b class="evidence-warn">待选</b></div>
                  </div>
                  <div class="evidence-callout"><span>i</span><p>当前结果不会进入正式健康状态。确认、修正、拒绝三种动作均会留下审计记录。</p></div>
                  <div class="evidence-actions"><button class="mini-action action-primary" type="button" @click="showToast('原型动作：进入人工确认流程')">进入复核 ↗</button><button class="mini-action" type="button" @click="showToast('原型动作：保持待补拍')">补拍</button></div>
                </section>
              </div>

              <div v-else class="page-map-grid">
                <button v-for="page in pages" :key="page[0]" class="page-map-card" type="button" @click="showToast(`${page[1]}：${page[2]}`)">
                  <span class="page-map-icon">{{ page[3] }}</span><span class="page-map-code">{{ page[0] }}</span><strong>{{ page[1] }}</strong><p>{{ page[2] }}</p><span class="page-map-arrow">↗</span>
                </button>
              </div>
            </div>
          </div>
        </div>
      </section>

      <section class="principles-section section-width" aria-labelledby="principles-heading">
        <div class="section-heading principle-heading">
          <div><span class="section-number">03 / 设计底线</span><h2 id="principles-heading">风格可以变，边界不能变。</h2></div>
          <p>十个候选都使用相同的产品硬承诺，选定后可继续接入真实状态与 API。</p>
        </div>
        <div class="principle-grid">
          <article class="principle-card"><span class="principle-icon">⌂</span><div><span>01 / PRIVACY</span><h3>健康数据默认不出网</h3><p>顶部常驻本地可信域状态；网络、天气与云端扩展都要可见、可审计。</p></div></article>
          <article class="principle-card"><span class="principle-icon">✓</span><div><span>02 / CONFIRMATION</span><h3>识别结果必须人工确认</h3><p>MATCHED、CONFLICT、UNKNOWN、REVIEW 都先留在待处理状态。</p></div></article>
          <article class="principle-card"><span class="principle-icon">✦</span><div><span>03 / EVIDENCE</span><h3>先依据，再解释</h3><p>风险等级来自规则；助手没有事实、规则和文档引用时应拒答。</p></div></article>
        </div>
        <div class="boundary-note"><span class="boundary-symbol">!</span><span><strong>教学演示，不替代医疗诊断。</strong> 家健镜不提供诊断、处方、停药、换药、剂量判断、购药、问诊或广告导流。</span><span class="boundary-code">BOUNDARY / P0</span></div>
      </section>
    </main>

    <footer class="site-footer section-width">
      <span>家健镜 HomeCare Twin · P0 UI concept board</span>
      <span>当前方向：{{ selectedDesign.name }} · 仅用于视觉评选</span>
    </footer>

    <Transition name="toast"><div v-if="toast" class="toast" role="status">{{ toast }}</div></Transition>
  </div>
</template>
