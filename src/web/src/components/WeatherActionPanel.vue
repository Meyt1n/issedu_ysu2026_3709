<script setup lang="ts">
import { computed } from 'vue'

import type { WeatherResponse } from '../api/types'
import { presentWeather } from '../weather/weatherView'
import AppIcon from './AppIcon.vue'

const props = withDefaults(
  defineProps<{
    weather: WeatherResponse | null
    loading?: boolean
  }>(),
  { loading: false },
)

const emit = defineEmits<{ refresh: [] }>()
const view = computed(() => presentWeather(props.weather))

const conditionLabels: Record<string, string> = {
  clear: '晴朗',
  sunny: '晴',
  cloudy: '多云',
  rain: '雨',
  snow: '雪',
  storm: '风暴',
  thunderstorm: '雷雨',
}

const conditionLabel = computed(() => {
  const condition = props.weather?.condition
  if (!condition) return '暂无描述'
  return conditionLabels[condition.toLowerCase()] ?? condition
})
</script>

<template>
  <section class="weather-action-panel" aria-labelledby="weather-action-title">
    <header class="weather-action-head">
      <div>
        <span class="weather-eyebrow"><AppIcon name="cloud" :size="15" />家庭环境行动卡</span>
        <h3 id="weather-action-title">今日环境与可执行提醒</h3>
      </div>
      <div class="weather-head-actions">
        <span class="pill" :class="view.statusTone">{{ view.statusLabel }}</span>
        <button
          type="button"
          class="btn btn-ghost btn-small"
          :disabled="loading"
          :aria-busy="loading"
          @click="emit('refresh')"
        >
          <AppIcon name="refresh" :size="14" />
          {{ loading ? '刷新中' : '刷新天气' }}
        </button>
      </div>
    </header>

    <div v-if="view.available" class="weather-action-body">
      <div class="weather-reading" :class="{ stale: view.stale }">
        <span class="weather-temperature">
          {{ weather?.temperature != null ? `${weather.temperature}°` : '—' }}
        </span>
        <div class="weather-reading-copy">
          <strong>{{ conditionLabel }}</strong>
          <span>
            湿度 {{ weather?.humidity != null ? `${weather.humidity}%` : '暂无' }}
            · AQI {{ weather?.aqi ?? '暂无' }}
          </span>
          <span v-if="weather?.wind">风况 {{ weather.wind }}</span>
        </div>
      </div>

      <div class="weather-card-list" aria-live="polite">
        <article
          v-for="(card, index) in weather?.action_cards ?? []"
          :key="card.rule_id ?? index"
          class="weather-advice"
          :class="card.level === 'warning' ? 'warning' : 'info'"
        >
          <AppIcon :name="card.level === 'warning' ? 'alert' : 'info'" :size="18" />
          <div>
            <strong>{{ card.level === 'warning' ? '需要留意' : '生活安排建议' }}</strong>
            <p>{{ card.message }}</p>
          </div>
        </article>
        <div v-if="(weather?.action_cards.length ?? 0) === 0" class="weather-calm">
          <AppIcon name="check" :size="18" />
          <span>当前没有触发已审核的环境行动规则。</span>
        </div>
      </div>
    </div>

    <div v-else class="weather-unavailable" role="status">
      <AppIcon name="cloud" :size="28" />
      <div>
        <strong>{{ view.statusLabel }}</strong>
        <p>{{ view.detail }}</p>
      </div>
    </div>

    <footer class="weather-evidence">
      <span><AppIcon name="lock" :size="13" />{{ view.scopeLabel }}，不发送精确住址或成员健康信息</span>
      <span><AppIcon name="clock" :size="13" />{{ view.sourceLabel }}</span>
      <span>规则 {{ weather?.ruleset_version ?? '待配置' }}</span>
      <p v-if="view.stale" class="weather-degraded">{{ view.detail }}</p>
      <p>{{ weather?.disclaimer ?? '环境行动建议仅供日常生活安排参考，不构成诊断或用药建议。' }}</p>
    </footer>
  </section>
</template>
