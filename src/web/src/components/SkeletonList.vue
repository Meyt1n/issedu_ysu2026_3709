<script setup lang="ts">
const props = defineProps<{
  rows?: number
  variant?: 'timeline' | 'cards'
}>()

const count = props.rows ?? 4
</script>

<template>
  <div class="skeleton-stack" role="status" aria-label="正在读取已授权数据">
    <template v-if="(variant ?? 'timeline') === 'timeline'">
      <div v-for="row in count" :key="row" class="skeleton-row">
        <span class="skeleton skeleton-dot" />
        <span class="skeleton-lines">
          <span class="skeleton skeleton-line" :style="{ width: `${52 + ((row * 17) % 34)}%` }" />
          <span class="skeleton skeleton-line thin" :style="{ width: `${30 + ((row * 23) % 28)}%` }" />
        </span>
      </div>
    </template>
    <template v-else>
      <span
        v-for="row in count"
        :key="row"
        class="skeleton skeleton-card"
      />
    </template>
  </div>
</template>
