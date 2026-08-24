<script setup lang="ts">
import { computed, ref } from 'vue'
import { useRouter } from 'vue-router'

import AppIcon from '@/components/AppIcon.vue'
import { clearLocalData, controlledWebHandoff, usePrivacy } from '@/stores/privacy'

const router = useRouter()
const { session, entries, noticeVersion } = usePrivacy()
const clearConfirmOpen = ref(false)
const clearMessage = ref('')
const clearError = ref(false)
const handoffUrl = computed(() => controlledWebHandoff(session.serverBaseUrl))

function requestClear(): void {
  clearConfirmOpen.value = true
  clearMessage.value = ''
  clearError.value = false
}

function cancelClear(): void {
  clearConfirmOpen.value = false
}

function confirmClear(): void {
  const result = clearLocalData()
  clearConfirmOpen.value = false
  clearError.value = !result.ok
  clearMessage.value = result.message
}
</script>

<template>
  <main id="main" class="screen">
    <button type="button" class="btn btn-quiet back-btn" @click="router.back()">
      <AppIcon name="arrow-left" :size="18" />
      返回
    </button>

    <header class="screen-header">
      <p class="eyebrow">隐私与数据权利</p>
      <h1>本地数据管理</h1>
      <p class="screen-subtitle">隐私告知版本 {{ noticeVersion }}。移动端只管理本机设置，不替代服务端健康数据删除或导出流程。</p>
    </header>

    <section class="card" aria-labelledby="notice-title">
      <div class="h-icon-row">
        <span class="row-icon" data-tone="calm" aria-hidden="true"><AppIcon name="shield" :size="16" /></span>
        <h2 id="notice-title">当前隐私边界</h2>
      </div>
      <ul class="divided-list">
        <li>演示模式只使用虚构数据；联机模式只连接你配置的家庭服务器。</li>
        <li>正式登录凭据、密码、PIN 和健康正文不写入 localStorage。</li>
        <li>联系人和服务器地址仅用于本机设置与主动拨号/联机，不上传到健康事件。</li>
        <li>视觉模型和健康事实仍由网页端/家庭服务器处理；本应用不在本地保存模型权重。</li>
      </ul>
    </section>

    <section class="card" aria-labelledby="stored-title">
      <h2 id="stored-title">本机保存清单</h2>
      <ul class="divided-list privacy-data-list">
        <li v-for="entry in entries" :key="entry.id">
          <div class="card-title-row">
            <strong>{{ entry.label }}</strong>
            <span class="tag" :data-tone="entry.sensitive ? 'warn' : 'calm'">{{ entry.persistence }}</span>
          </div>
          <span class="meta-line">{{ entry.detail }}</span>
        </li>
      </ul>
    </section>

    <section class="card" aria-labelledby="rights-title">
      <h2 id="rights-title">导出、删除与撤权</h2>
      <p class="meta-line">这些操作必须由家庭服务器或网页端按授权、目的和审计规则办理；移动端不会复制健康数据，也不会伪造完成状态。</p>
      <a v-if="handoffUrl" class="btn btn-quiet btn-block" :href="handoffUrl" target="_blank" rel="noreferrer">
        <AppIcon name="chevron-right" :size="18" />
        打开受控家庭网页端
      </a>
      <p v-else class="notice" data-tone="warn" role="status">当前没有可验证的 HTTPS 家庭服务器地址，请先到“我的”完成联机配置。</p>
    </section>

    <section class="card" aria-labelledby="clear-title">
      <h2 id="clear-title">清理本机设置</h2>
      <p class="meta-line">清理会移除联系人、服务器地址、开发期身份、成员选择、无障碍偏好和运行时能力状态；不会删除家庭服务器上的健康事实。</p>
      <button type="button" class="btn btn-danger btn-block" @click="requestClear">清理本机设置</button>
      <p v-if="clearMessage" class="notice" :data-tone="clearError ? 'error' : 'success'" role="status">{{ clearMessage }}</p>
    </section>

    <div v-if="clearConfirmOpen" class="dialog-backdrop" @click.self="cancelClear">
      <section class="confirm-dialog card" role="dialog" aria-modal="true" aria-labelledby="clear-dialog-title" aria-describedby="clear-dialog-description">
        <h2 id="clear-dialog-title">确认清理本机设置？</h2>
        <p id="clear-dialog-description">清理后需要重新选择模式、服务器和联系人。服务器上的健康数据不会被删除。</p>
        <div class="btn-row dialog-actions">
          <button type="button" class="btn btn-danger" @click="confirmClear">确认清理</button>
          <button type="button" class="btn btn-quiet" @click="cancelClear">取消</button>
        </div>
      </section>
    </div>
  </main>
</template>

<style scoped>
.privacy-data-list { margin: 0; }
.privacy-data-list li { display: grid; gap: 5px; }
</style>
