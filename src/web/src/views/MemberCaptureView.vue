<script setup lang="ts">
import { ref } from 'vue'

import type { VisionTask } from '../api/types'
import AppIcon from '../components/AppIcon.vue'
import VisionQualityPanel from '../vision/VisionQualityPanel.vue'
import { pushToast, session } from '../store'

const submittedTask = ref<VisionTask | null>(null)

function onTaskCreated(task: VisionTask): void {
  submittedTask.value = task
  pushToast('success', '照片已提交，等家庭管理员确认后才会记入家庭记录。')
}
</script>

<template>
  <section class="page-hero member-portal-hero">
    <p class="eyebrow">拍照录药</p>
    <h2 class="hero-greeting">把药盒拍清楚就可以了</h2>
    <p class="hero-sub">你只需要拍照并提交，药品名称和用法由家庭管理员检查后再保存。</p>
  </section>

  <p class="notice ok member-confirmation-note" role="status">
    <AppIcon name="lock" :size="16" />
    你提交的是待确认照片，不会直接写进健康记录。
  </p>

  <VisionQualityPanel
    :actor-id="session.actorId"
    :member-id="session.selectedMemberId || undefined"
    :access-purpose="session.accessPurpose"
    audience="member"
    @task-created="onTaskCreated"
  />

  <section v-if="submittedTask" class="card member-next-step">
    <AppIcon name="check" :size="22" />
    <div><strong>接下来由家庭管理员确认</strong><p>确认后，你可以在“我的记录”里看到结果。</p></div>
  </section>
</template>
