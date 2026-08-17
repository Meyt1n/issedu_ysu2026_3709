<script setup lang="ts">
export type IconName =
  | 'home'
  | 'camera'
  | 'family'
  | 'bell'
  | 'user'
  | 'shield'
  | 'sound'
  | 'check'
  | 'clock'
  | 'alert'
  | 'chevron-right'
  | 'arrow-left'
  | 'settings'
  | 'phone'
  | 'refresh'
  | 'eye'
  | 'heart'
  | 'pill'

const props = withDefaults(
  defineProps<{
    name: IconName
    size?: number
  }>(),
  { size: 22 },
)

const PATHS: Record<IconName, string[]> = {
  home: ['M3 11 12 4l9 7', 'M5 10v10h14V10'],
  camera: ['M4 8h4l1.6-3h4.8L16 8h4v12H4z', 'M12 17.5A3.5 3.5 0 1 0 12 10.5a3.5 3.5 0 0 0 0 7z'],
  family: [
    'M9 11a3 3 0 1 0 0-6 3 3 0 0 0 0 6z',
    'M3.5 20c0-3 2.4-5 5.5-5s5.5 2 5.5 5',
    'M17 11.5a2.5 2.5 0 1 0 0-5 2.5 2.5 0 0 0 0 5z',
    'M15.5 20c.2-2.6 2-4.2 4.9-4.2',
  ],
  bell: ['M6 9a6 6 0 0 1 12 0c0 5 2 6 2 6H4s2-1 2-6z', 'M10 19a2 2 0 0 0 4 0'],
  user: ['M12 12a4 4 0 1 0 0-8 4 4 0 0 0 0 8z', 'M4 21c0-4 3.5-6.5 8-6.5s8 2.5 8 6.5'],
  shield: ['M12 3l8 3v6c0 5-3.5 8-8 9.5C7.5 20 4 17 4 12V6z', 'M9 11.5l2.2 2.2L15.5 9'],
  sound: ['M4 10v4h4l5 4V6l-5 4z', 'M16 9a4 4 0 0 1 0 6', 'M18.5 6.5a8 8 0 0 1 0 11'],
  check: ['M5 13l4.5 4.5L19 7'],
  clock: ['M12 21a9 9 0 1 0 0-18 9 9 0 0 0 0 18z', 'M12 7v5l3.5 2'],
  alert: ['M12 3L22 20H2z', 'M12 9.5V14', 'M12 16.8v.4'],
  'chevron-right': ['M9 5l7 7-7 7'],
  'arrow-left': ['M19 12H5', 'M11 5l-7 7 7 7'],
  settings: [
    'M12 15a3 3 0 1 0 0-6 3 3 0 0 0 0 6z',
    'M12 2.5v3M12 18.5v3M2.5 12h3M18.5 12h3M5 5l2.1 2.1M16.9 16.9L19 19M19 5l-2.1 2.1M7.1 16.9L5 19',
  ],
  phone: [
    'M5 4h4l1.6 4.6-2.5 1.6a12.5 12.5 0 0 0 5.7 5.7l1.6-2.5L20 15v4a1.6 1.6 0 0 1-1.8 1.6A16.5 16.5 0 0 1 3.4 5.8 1.6 1.6 0 0 1 5 4z',
  ],
  refresh: ['M20 12a8 8 0 1 1-2.3-5.7', 'M20 3.5V8h-4.5'],
  eye: ['M2 12s3.5-6.5 10-6.5S22 12 22 12s-3.5 6.5-10 6.5S2 12 2 12z', 'M12 14.8a2.8 2.8 0 1 0 0-5.6 2.8 2.8 0 0 0 0 5.6z'],
  heart: ['M12 20c-6-4.5-9-7.4-9-11a5 5 0 0 1 9-2.6A5 5 0 0 1 21 9c0 3.6-3 6.5-9 11z'],
  pill: [
    'M8.7 4.2a5.4 5.4 0 0 1 7.6 0l3.5 3.5a5.4 5.4 0 0 1 0 7.6l-4.5 4.5a5.4 5.4 0 0 1-7.6 0l-3.5-3.5a5.4 5.4 0 0 1 0-7.6z',
    'M6.9 9.6l7.5 7.5',
  ],
}
</script>

<template>
  <svg
    :width="props.size"
    :height="props.size"
    viewBox="0 0 24 24"
    fill="none"
    stroke="currentColor"
    stroke-width="2"
    stroke-linecap="round"
    stroke-linejoin="round"
    aria-hidden="true"
    focusable="false"
  >
    <path v-for="(d, index) in PATHS[props.name]" :key="index" :d="d" />
  </svg>
</template>
