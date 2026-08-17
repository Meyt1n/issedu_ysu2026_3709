<script setup lang="ts">
import { computed, ref } from 'vue'

import AppIcon from '@/components/AppIcon.vue'
import { createSpeaker } from '@/composables/useSpeech'
import { activeProvider } from '@/data'
import { riskLevelLabel } from '@/data/labels'
import { useSession } from '@/stores/session'

const { session } = useSession()
const manualSpeaker = createSpeaker(() => true)
const speaking = ref(false)

const phoneHref = computed(() =>
  session.caregiverPhone ? `tel:${session.caregiverPhone.replace(/\s+/g, '')}` : '',
)

async function speakImportant(): Promise<void> {
  speaking.value = true
  try {
    const risks = await activeProvider().listRisks()
    const important = risks.filter(r => (r.level === 'SEVERE' || r.level === 'WARNING') && !r.acknowledged)
    if (important.length === 0) {
      manualSpeaker.speak('当前没有严重或较高等级的风险提醒。')
      return
    }
    const text = important.map(r => `${riskLevelLabel(r.level)}：${r.memberName}，${r.message}`).join('。')
    manualSpeaker.speak(`共有 ${important.length} 条重要提醒。${text}。`)
  } catch {
    manualSpeaker.speak('提醒信息暂时无法读取。')
  } finally {
    speaking.value = false
  }
}
</script>

<template>
  <main id="main" class="screen">
    <header class="screen-header">
      <p class="eyebrow">紧急情况</p>
      <h1>求助</h1>
      <p class="screen-subtitle">如果感到严重不适，请立即拨打急救电话或联系家人，不要等待应用提示。</p>
    </header>

    <a class="btn btn-lg btn-block emergency-btn" href="tel:120">
      <AppIcon name="phone" :size="24" />
      拨打急救电话 120
    </a>
    <p class="meta-line">点按后会打开手机拨号界面；本应用是教学演示，请在真实紧急情况下拨打。</p>

    <a v-if="phoneHref" class="btn btn-lg btn-block" :href="phoneHref">
      <AppIcon name="family" :size="24" />
      联系家人{{ session.caregiverName ? `：${session.caregiverName}` : '' }}（{{ session.caregiverPhone }}）
    </a>
    <div v-else class="card">
      <p class="notice" data-tone="warn">还没有设置紧急联系人。</p>
      <RouterLink class="btn btn-quiet btn-block" to="/me">去「我的」页设置家人电话</RouterLink>
    </div>

    <button type="button" class="btn btn-quiet btn-lg btn-block" :disabled="speaking" @click="speakImportant">
      <AppIcon name="sound" :size="22" />
      {{ speaking ? '正在读取…' : '语音播报当前重要提醒' }}
    </button>

    <section class="card">
      <h2>拨号前可以准备什么</h2>
      <ul class="divided-list">
        <li>说清楚人在哪里（小区、楼栋、门牌号）。</li>
        <li>说明谁不舒服、大概什么症状、从什么时候开始。</li>
        <li>如方便，告知正在服用的药物（可在“家人”页查看获授权的用药记录）。</li>
      </ul>
    </section>

    <footer class="disclaimer">
      家健镜不提供在线问诊或购药入口；紧急情况请始终以医生和急救服务的判断为准。
    </footer>
  </main>
</template>

<style scoped>
.emergency-btn {
  background: linear-gradient(135deg, #de7263 0%, #d2604f 55%, #b84c3b 100%);
  color: #fff;
  box-shadow: 0 12px 26px -12px rgba(210, 96, 79, 0.65);
  animation: sos-pulse 2.6s var(--ease) infinite;
}
.emergency-btn:hover { filter: brightness(1.08); }
html[data-contrast='high'] .emergency-btn {
  background: var(--c-danger);
  box-shadow: none;
  border: 2px solid #000;
  animation: none;
}
</style>
