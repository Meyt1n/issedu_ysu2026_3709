<script setup lang="ts">
import { computed, ref } from 'vue'

import type { HealthEvent, PlanWorkbenchItem, ReviewTask } from '../api/types'
import AppIcon from '../components/AppIcon.vue'
import {
  bucketByDay,
  calendarMonthLabel,
  calendarWeekdayLabels,
  dayBucketTotal,
  dayKeyOf,
  daySummaryLabel,
  monthMatrix,
  shiftMonth,
  type DayBucket,
} from '../overview/healthCalendar'

const props = defineProps<{
  events: HealthEvent[]
  plans: PlanWorkbenchItem[]
  reviews: ReviewTask[]
}>()

const today = new Date()
const viewYear = ref(today.getFullYear())
const viewMonth = ref(today.getMonth() + 1)

const cells = computed(() => monthMatrix(viewYear.value, viewMonth.value))
const monthLabel = computed(() => calendarMonthLabel(viewYear.value, viewMonth.value))
const buckets = computed(() => bucketByDay(props.events, props.plans, props.reviews))
const todayKey = computed(() => dayKeyOf(new Date()))
const activeDayCount = computed(() =>
  [...buckets.value.values()].filter(bucket => dayBucketTotal(bucket) > 0).length,
)

const selectedKey = ref<string | null>(null)
const selectedBucket = computed<DayBucket | null>(() =>
  selectedKey.value ? buckets.value.get(selectedKey.value) ?? null : null,
)

function markCount(key: string | null): number {
  if (!key) return 0
  return dayBucketTotal(buckets.value.get(key))
}

function markTone(key: string | null): string {
  const bucket = key ? buckets.value.get(key) : null
  if (!bucket || dayBucketTotal(bucket) === 0) return ''
  if (bucket.events > 0) return 'pine'
  if (bucket.plans > 0) return 'gold'
  return 'clay'
}

function selectDay(key: string | null): void {
  if (!key) return
  selectedKey.value = selectedKey.value === key ? null : key
}

function shiftView(delta: number): void {
  const next = shiftMonth(viewYear.value, viewMonth.value, delta)
  viewYear.value = next.year
  viewMonth.value = next.month
  selectedKey.value = null
}

function backToToday(): void {
  viewYear.value = today.getFullYear()
  viewMonth.value = today.getMonth() + 1
  selectedKey.value = todayKey.value
}
</script>

<template>
  <section
    class="home-dashboard-card overview-section overview-section--calendar"
    aria-labelledby="calendar-overview-title"
  >
    <div class="sec-head">
      <span class="overview-sec-icon" aria-hidden="true"><AppIcon name="plan" :size="15" /></span>
      <h3 id="calendar-overview-title">健康日历</h3>
      <span class="calendar-head-note">
        <i aria-hidden="true" />本月 {{ activeDayCount }} 天有记录
      </span>
      <span class="sec-line" />
      <button type="button" class="btn btn-ghost btn-small" @click="backToToday">
        回到今天
      </button>
    </div>

    <div class="calendar-toolbar">
      <button type="button" class="calendar-nav" title="上一个月" aria-label="上一个月" @click="shiftView(-1)">‹</button>
      <strong class="calendar-month">{{ monthLabel }}</strong>
      <button type="button" class="calendar-nav" title="下一个月" aria-label="下一个月" @click="shiftView(1)">›</button>
    </div>

    <!--
      不用 role="grid"：那要求 row/gridcell 子结构，也向读屏承诺方向键导航，
      而本组件并未实现。每个日期按钮自带完整 aria-label（年月日 + 当日摘要），
      用 group 如实描述「一组可点的日期按钮」。
    -->
    <div class="calendar-grid" role="group" aria-label="健康日历网格">
      <span v-for="label in calendarWeekdayLabels()" :key="label" class="calendar-weekday" aria-hidden="true">
        {{ label }}
      </span>
      <template v-for="(cell, index) in cells" :key="cell.key ?? `blank-${index}`">
        <span v-if="!cell.key" class="calendar-cell blank" aria-hidden="true" />
        <button
          v-else
          type="button"
          class="calendar-cell"
          :class="{ today: cell.key === todayKey, selected: cell.key === selectedKey }"
          :aria-label="`${viewYear}年${viewMonth}月${cell.day}日，${daySummaryLabel(buckets.get(cell.key))}`"
          @click="selectDay(cell.key)"
        >
          <span class="calendar-day">{{ cell.day }}</span>
          <span
            v-if="markCount(cell.key) > 0"
            class="calendar-mark"
            :class="markTone(cell.key)"
          >
            {{ markCount(cell.key) > 9 ? '9+' : markCount(cell.key) }}
          </span>
        </button>
      </template>
    </div>

    <div class="calendar-legend" aria-hidden="true">
      <span><i class="legend-dot pine" />事件</span>
      <span><i class="legend-dot gold" />用药</span>
      <span><i class="legend-dot clay" />识别复核</span>
    </div>

    <p class="calendar-summary" aria-live="polite">
      <template v-if="selectedKey">
        {{ viewMonth }}月{{ Number(selectedKey.slice(-2)) }}日：{{ daySummaryLabel(selectedBucket) }}
      </template>
      <template v-else>点选日期查看当日摘要。</template>
    </p>
  </section>
</template>

<style scoped>
.calendar-toolbar {
  align-items: center;
  display: flex;
  gap: 12px;
  justify-content: center;
  margin: 4px 0 12px;
}

.calendar-month {
  color: var(--ink, #3f3a31);
  /* 年份数字与「年/月」用同一字体栈，避免数字衬线、中文回退系统字的混排感。 */
  font-family: var(--font-display, Georgia, serif);
  font-size: 17px;
  min-width: 92px;
  text-align: center;
}

.calendar-nav {
  align-items: center;
  background: rgba(255, 255, 255, 0.55);
  border: 1px solid rgba(190, 167, 125, 0.3);
  border-radius: 50%;
  color: var(--ink-soft, #6d6659);
  cursor: pointer;
  display: inline-flex;
  font-size: 17px;
  height: 30px;
  justify-content: center;
  line-height: 1;
  padding: 0;
  transition: border-color 160ms ease, background 160ms ease, color 160ms ease;
  width: 30px;
}

.calendar-nav:hover,
.calendar-nav:focus-visible {
  background: rgba(238, 247, 239, 0.85);
  border-color: rgba(52, 104, 88, 0.45);
  color: var(--pine, #38665a);
  outline: none;
}

.calendar-grid {
  display: grid;
  gap: 4px;
  grid-template-columns: repeat(7, minmax(0, 1fr));
}

.calendar-weekday {
  color: var(--ink-faint, #877966);
  font-size: 11.5px;
  padding: 2px 0 4px;
  text-align: center;
}

.calendar-cell {
  align-items: center;
  background: transparent;
  border: 1px solid transparent;
  border-radius: 10px;
  cursor: pointer;
  display: flex;
  flex-direction: column;
  gap: 1px;
  justify-content: center;
  min-height: 46px;
  padding: 5px 2px 4px;
  transition: background 160ms ease, border-color 160ms ease;
}

/* 补位空格完全透明：只占网格位，不显示任何方框。 */
.calendar-cell.blank {
  background: none;
  border: 0;
  min-height: 0;
  padding: 0;
  pointer-events: none;
}

.calendar-cell:not(.blank):hover,
.calendar-cell:not(.blank):focus-visible {
  background: rgba(238, 247, 239, 0.7);
  border-color: rgba(52, 104, 88, 0.35);
  outline: none;
}

.calendar-cell.today {
  border-color: rgba(194, 103, 68, 0.5);
}

.calendar-cell.selected {
  background: rgba(238, 247, 239, 0.9);
  border-color: rgba(52, 104, 88, 0.55);
}

.calendar-day {
  color: var(--ink, #3f3a31);
  font-size: 12.5px;
  line-height: 1;
}

.calendar-mark {
  border-radius: 999px;
  color: #fff;
  font-size: 9.5px;
  font-weight: 600;
  line-height: 1;
  padding: 2.5px 5.5px;
}

.calendar-mark.pine { background: var(--pine, #38665a); }
.calendar-mark.gold { background: var(--gold, #a97e1f); }
.calendar-mark.clay { background: var(--clay, #c26744); }

.calendar-legend {
  color: var(--ink-soft, #6d6659);
  display: flex;
  font-size: 11.5px;
  gap: 14px;
  margin-top: 12px;
}

.calendar-legend span {
  align-items: center;
  display: inline-flex;
  gap: 5px;
}

.legend-dot {
  border-radius: 50%;
  display: inline-block;
  height: 8px;
  width: 8px;
}

.legend-dot.pine { background: var(--pine, #38665a); }
.legend-dot.gold { background: var(--gold, #a97e1f); }
.legend-dot.clay { background: var(--clay, #c26744); }

.calendar-summary {
  background: rgba(255, 255, 255, 0.45);
  border: 1px solid rgba(190, 167, 125, 0.22);
  border-radius: 12px;
  color: var(--ink-soft, #6d6659);
  font-size: 12.5px;
  margin: 10px 0 0;
  padding: 9px 12px;
}
</style>
