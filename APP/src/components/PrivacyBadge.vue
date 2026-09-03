<script setup lang="ts">
import { computed } from 'vue'

import AppIcon from '@/components/AppIcon.vue'
import { useSession } from '@/stores/session'

const { session } = useSession()

const text = computed(() =>
  session.dataMode === 'demo'
    ? '本地数据 · 不联网'
    : '家庭服务器 · 默认不出网',
)
</script>

<template>
  <p class="privacy-badge">
    <AppIcon name="shield" :size="16" />
    {{ text }}
  </p>
</template>
