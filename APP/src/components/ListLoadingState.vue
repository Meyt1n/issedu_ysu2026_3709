<script setup lang="ts">
import SkeletonCard from '@/components/SkeletonCard.vue'

withDefaults(
  defineProps<{
    /** 供 TalkBack/读屏器播报的当前列表状态。 */
    label: string
    /** 占位卡片数量；只表示布局，不代表真实数据条数。 */
    count?: number
    /** 是否显示左侧图标/头像占位。 */
    disc?: boolean
  }>(),
  { count: 3, disc: true },
)
</script>

<template>
  <div class="list-loading" role="status" aria-live="polite" aria-busy="true">
    <p class="meta-line">{{ label }}</p>
    <SkeletonCard v-for="index in count" :key="index" :disc="disc" />
  </div>
</template>

<style scoped>
.list-loading {
  display: grid;
  gap: 12px;
}

.list-loading > .meta-line {
  margin: 0;
}
</style>
