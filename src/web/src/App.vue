<script setup lang="ts">
import { onMounted, ref } from 'vue'

type HealthState = {
  status: string
  service: string
  version: string
}

const health = ref<HealthState | null>(null)
const loading = ref(true)
const error = ref('')

onMounted(async () => {
  try {
    const response = await fetch('/health')
    if (!response.ok) throw new Error(`API ${response.status}`)
    health.value = (await response.json()) as HealthState
  } catch (cause) {
    error.value = cause instanceof Error ? cause.message : 'API 暂不可用'
  } finally {
    loading.value = false
  }
})
</script>

<template>
  <main class="shell">
    <header class="topbar">
      <div>
        <p class="eyebrow">HOMECARE TWIN · P0 FOUNDATION</p>
        <h1>家健镜</h1>
        <p class="subtitle">家庭健康事件孪生与本地智能照护平台</p>
      </div>
      <div class="privacy-badge">健康数据默认保存在本地家庭可信域</div>
    </header>

    <section class="hero card">
      <div>
        <span class="tag">一期纵向增量</span>
        <h2>先把事实、授权和事件链做可靠。</h2>
        <p>
          当前版本支持健康服务检查、家庭/成员骨架、字段级照护授权和手工确认事件。
          视觉、RAG、LLM、天气和风险规则暂时明确降级，不伪造结果。
        </p>
      </div>
      <div class="status-panel">
        <span class="status-dot" :class="{ ready: health?.status === 'ok' }"></span>
        <strong>{{ loading ? '正在检查 API' : health ? 'API 已连接' : 'API 不可用' }}</strong>
        <small v-if="health">{{ health.service }} · v{{ health.version }}</small>
        <small v-else-if="error">{{ error }}</small>
      </div>
    </section>

    <section class="grid">
      <article class="card">
        <p class="card-label">已建立</p>
        <h3>事实与授权骨架</h3>
        <ul>
          <li>MySQL 事实主库与 Alembic 迁移</li>
          <li>家庭、成员和照护授权</li>
          <li>不可覆盖健康事件与 outbox</li>
          <li>成员状态投影与可追溯时间线</li>
        </ul>
      </article>
      <article class="card muted-card">
        <p class="card-label">明确不可用</p>
        <h3>AI 能力保持诚实降级</h3>
        <ul>
          <li>YOLO / OCR / 条码适配器</li>
          <li>RAG / Ollama / QLoRA</li>
          <li>天气行动卡与风险规则</li>
          <li>真实医疗判断与导流入口</li>
        </ul>
      </article>
    </section>

    <footer>教学演示，不替代医疗诊断、处方或专业照护。</footer>
  </main>
</template>
