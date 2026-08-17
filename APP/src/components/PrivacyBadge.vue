<script setup lang="ts">
import { computed } from 'vue'

import AppIcon from '@/components/AppIcon.vue'
import { useSession } from '@/stores/session'

const { session } = useSession()

const text = computed(() =>
  session.dataMode === 'demo'
    ? '演示数据（虚构）· 健康数据不出网'
    : '本地家庭服务器 · 健康数据默认不出网',
)
</script>

<template>
  <p class="privacy-badge">
    <AppIcon name="shield" :size="16" />
    {{ text }}
  </p>
</template>
