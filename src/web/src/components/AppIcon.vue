<script setup lang="ts">
import { computed } from 'vue'

const props = defineProps<{
  name: string
  size?: number
}>()

const ICONS: Record<string, string> = {
  home: '<path d="M4 11.2 12 4.5l8 6.7"/><path d="M6 9.8V19a1 1 0 0 0 1 1h10a1 1 0 0 0 1-1V9.8"/><path d="M12 16.6s-2.6-1.7-2.6-3.4c0-.9.7-1.6 1.5-1.6.5 0 .9.2 1.1.6.2-.4.6-.6 1.1-.6.8 0 1.5.7 1.5 1.6 0 1.7-2.6 3.4-2.6 3.4Z"/>',
  members: '<circle cx="9" cy="8.5" r="3"/><path d="M3.5 19.5c.6-3.2 2.8-5 5.5-5s4.9 1.8 5.5 5"/><circle cx="16.5" cy="9.5" r="2.3"/><path d="M16.1 14.6c2.3.2 4 1.8 4.4 4.4"/>',
  scan: '<path d="M4 8V5.5A1.5 1.5 0 0 1 5.5 4H8"/><path d="M16 4h2.5A1.5 1.5 0 0 1 20 5.5V8"/><path d="M20 16v2.5a1.5 1.5 0 0 1-1.5 1.5H16"/><path d="M8 20H5.5A1.5 1.5 0 0 1 4 18.5V16"/><rect x="8" y="9" width="8" height="6.5" rx="1.2"/><path d="M10.5 9V8a1.5 1.5 0 0 1 3 0v1"/>',
  review: '<path d="M9 5h9.5v14.5H5.5V5H9"/><path d="M9 4h6v2.5H9z"/><path d="m8.5 12 2 2 4.5-4.5"/><path d="M8.5 17h7"/>',
  shield: '<path d="M12 3.5 5 6v5.2c0 4.6 3 7.6 7 9.3 4-1.7 7-4.7 7-9.3V6l-7-2.5Z"/><path d="M8.5 12h2l1-2 1.5 4 1-2h1.5"/>',
  plan: '<rect x="4" y="5.5" width="16" height="15" rx="1.5"/><path d="M8 3.5v4M16 3.5v4M4 10h16"/><path d="m9.5 15 2 2 3.5-3.5"/>',
  assistant: '<path d="M12 4c-4.4 0-8 2.9-8 6.6 0 2 1.1 3.9 2.9 5.1L6 20l3.8-1.6c.7.1 1.4.2 2.2.2 4.4 0 8-2.9 8-6.6S16.4 4 12 4Z"/><path d="M12 8.3v.01M12 13.8v.01M9 11h.01M15 11h.01"/>',
  microphone: '<rect x="8" y="3.5" width="8" height="11" rx="4"/><path d="M5.5 11.5a6.5 6.5 0 0 0 13 0M12 18v3M8.5 21h7"/>',
  volume: '<path d="M4 10v4h3l4 3.5v-11L7 10H4Z"/><path d="M15 9a4 4 0 0 1 0 6M17.5 6.5a7.5 7.5 0 0 1 0 11"/>',
  key: '<circle cx="8" cy="15.5" r="4"/><path d="m11 12.5 8.5-8.5"/><path d="M16 8l2.5 2.5M18.5 5.5 21 8"/>',
  heart: '<path d="M12 20s-7.5-4.7-7.5-9.6C4.5 7.7 6.6 6 8.8 6c1.3 0 2.5.6 3.2 1.6C12.7 6.6 13.9 6 15.2 6c2.2 0 4.3 1.7 4.3 4.4C19.5 15.3 12 20 12 20Z"/>',
  leaf: '<path d="M5 19c0-8 4-13 14-14 .5 10-4 14-11.5 14"/><path d="M5 19c3-5 7-8.5 11-10.5"/>',
  lock: '<rect x="5.5" y="10.5" width="13" height="9.5" rx="1.5"/><path d="M8.5 10.5V8a3.5 3.5 0 0 1 7 0v2.5"/><path d="M12 14.5v2"/>',
  sun: '<circle cx="12" cy="12" r="4"/><path d="M12 3.5v2M12 18.5v2M3.5 12h2M18.5 12h2M6 6l1.4 1.4M16.6 16.6 18 18M18 6l-1.4 1.4M7.4 16.6 6 18"/>',
  refresh: '<path d="M19 12a7 7 0 1 1-2-4.9"/><path d="M17.5 3.5V7H14"/>',
  plus: '<path d="M12 5.5v13M5.5 12h13"/>',
  close: '<path d="m6 6 12 12M18 6 6 18"/>',
  trash: '<path d="M5 7h14M10 11v6M14 11v6M9 7V4.5h6V7M7 7l.8 13h8.4L17 7"/>',
  'arrow-right': '<path d="M4.5 12h15M14 6.5l5.5 5.5L14 17.5"/>',
  'arrow-up': '<path d="M12 19.5v-15M6.5 10 12 4.5 17.5 10"/>',
  upload: '<path d="M12 15.5v-11M7.5 9 12 4.5 16.5 9"/><path d="M4.5 15.5v3a1.5 1.5 0 0 0 1.5 1.5h12a1.5 1.5 0 0 0 1.5-1.5v-3"/>',
  alert: '<path d="M12 4 2.8 19.5h18.4L12 4Z"/><path d="M12 10v4M12 17v.01"/>',
  check: '<path d="m5 12.5 4.5 4.5L19 7.5"/>',
  info: '<circle cx="12" cy="12" r="8.5"/><path d="M12 11v5M12 8v.01"/>',
  clock: '<circle cx="12" cy="12" r="8.5"/><path d="M12 7.5V12l3 2"/>',
  sparkle: '<path d="M12 4.5 13.6 10 19 11.5 13.6 13 12 18.5 10.4 13 5 11.5 10.4 10 12 4.5Z"/><path d="M18.5 4.5v3M17 6h3"/>',
  cloud: '<path d="M7 18.5A4 4 0 0 1 7.5 10.6 5.5 5.5 0 0 1 18 12a3.5 3.5 0 0 1-.5 6.5H7Z"/>',
  pill: '<rect x="3.5" y="9" width="17" height="6.5" rx="3.25" transform="rotate(-30 12 12.25)"/><path d="m9 8.7 5.5 3.2"/>',
  eye: '<path d="M3 12s3.5-6 9-6 9 6 9 6-3.5 6-9 6-9-6-9-6Z"/><circle cx="12" cy="12" r="2.5"/>',
  timeline: '<path d="M6 4.5v15"/><circle cx="6" cy="7" r="1.6"/><circle cx="6" cy="13" r="1.6"/><path d="M9.5 7H19M9.5 13h6"/>',
  signout: '<path d="M14 4.5H6.5A1.5 1.5 0 0 0 5 6v12a1.5 1.5 0 0 0 1.5 1.5H14"/><path d="M10.5 12H20M16.5 8.5 20 12l-3.5 3.5"/>',
  compass: '<circle cx="12" cy="12" r="8.5"/><path d="m15 9-1.8 4.2L9 15l1.8-4.2L15 9Z"/>',
  palette: '<path d="M12 3.5c-4.7 0-8.5 3.8-8.5 8.5s3.8 8.5 8.5 8.5c1.4 0 2.3-1.1 2-2.4-.3-1.2.6-2.4 1.9-2.4h1.9c1.5 0 2.7-1.2 2.7-2.7C20.5 7.5 16.7 3.5 12 3.5Z"/><circle cx="8" cy="10.5" r="1.15"/><circle cx="12" cy="7.8" r="1.15"/><circle cx="16" cy="10.5" r="1.15"/>',
  settings: '<circle cx="12" cy="12" r="3"/><path d="M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 0 1-2.83 2.83l-.06-.06a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 2 0 0 1-4 0v-.09a1.65 1.65 0 0 0-1-1.51 1.65 1.65 0 0 0-1.82.33l-.06.06a2 2 0 0 1-2.83-2.83l.06-.06a1.65 1.65 0 0 0 .33-1.82 1.65 1.65 0 0 0-1.51-1H3a2 2 0 0 1 0-4h.09a1.65 1.65 0 0 0 1.51-1 1.65 1.65 0 0 0-.33-1.82l-.06-.06a2 2 0 0 1 2.83-2.83l.06.06a1.65 1.65 0 0 0 1.82.33h.08a1.65 1.65 0 0 0 1-1.51V3a2 2 0 0 1 4 0v.09a1.65 1.65 0 0 0 1 1.51h.08a1.65 1.65 0 0 0 1.82-.33l.06-.06a2 2 0 0 1 2.83 2.83l-.06.06a1.65 1.65 0 0 0-.33 1.82v.08a1.65 1.65 0 0 0 1.51 1H21a2 2 0 0 1 0 4h-.09a1.65 1.65 0 0 0-1.51 1Z"/>',
  history: '<path d="M4.5 5.5V9H8"/><path d="M4.7 9A8 8 0 1 1 4 12.5"/><path d="M12 8v4.5l3 1.8"/>',
}

const content = computed(() => ICONS[props.name] ?? ICONS.info)
const dimension = computed(() => props.size ?? 20)
</script>

<template>
  <svg
    class="app-icon"
    :width="dimension"
    :height="dimension"
    viewBox="0 0 24 24"
    fill="none"
    stroke="currentColor"
    stroke-width="1.7"
    stroke-linecap="round"
    stroke-linejoin="round"
    aria-hidden="true"
    v-html="content"
  />
</template>
