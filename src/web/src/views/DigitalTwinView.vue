<script setup lang="ts">
import { onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { apiClient } from '../api/client'
import type { DigitalTwinNode, DigitalTwinResponse } from '../api/types'
import AppIcon from '../components/AppIcon.vue'
import DigitalTwinGalaxy from '../components/digital-twin/DigitalTwinGalaxy.vue'
import { snapshotDelta } from '../digital-twin/galaxy-layout'
import type { GalaxyClusterId } from '../digital-twin/galaxy-types'
import { formatError, onHealthDataRefresh, requestOptions, session } from '../store'

const POLL_INTERVAL_MS = 20_000
const DELTA_VISIBLE_MS = 6_000
const emptyDelta = (): Record<GalaxyClusterId, number> => ({ family: 0, condition: 0, medicine: 0, conversation: 0, rag: 0, insight: 0 })
const twin = ref<DigitalTwinResponse | null>(null)
const loading = ref(false)
const syncing = ref(false)
const loadError = ref('')
const selectedNodeId = ref<string | null>(null)
const focusCluster = ref<GalaxyClusterId | null>(null)
const recentNodeIds = ref(new Set<string>())
const deltaCounts = ref(emptyDelta())
const showUnconfirmed = ref(true)
const autoOrbit = ref(true)
let pollTimer: ReturnType<typeof setInterval> | null = null
let deltaTimer: ReturnType<typeof setTimeout> | null = null
let removeHealthRefreshListener: (() => void) | null = null


function clearDeltaLater(): void {
  if (deltaTimer) clearTimeout(deltaTimer)
  deltaTimer = setTimeout(() => { recentNodeIds.value = new Set(); deltaCounts.value = emptyDelta() }, DELTA_VISIBLE_MS)
}

async function loadTwin(options: { silent?: boolean } = {}): Promise<void> {
  const householdId = session.selectedHouseholdId
  if (!householdId || syncing.value) return
  syncing.value = true
  if (!options.silent) loading.value = true
  loadError.value = ''
  try {
    const next = await apiClient.getDigitalTwin(householdId, requestOptions.value)
    if (twin.value) {
      const delta = snapshotDelta(twin.value, next)
      if (delta.addedNodeIds.size) { recentNodeIds.value = delta.addedNodeIds; deltaCounts.value = delta.counts; clearDeltaLater() }
    }
    twin.value = next
    if (selectedNodeId.value && !next.nodes.some(node => node.id === selectedNodeId.value)) selectedNodeId.value = null
  } catch (cause) {
    if (!options.silent || !twin.value) loadError.value = formatError(cause)
  } finally { syncing.value = false; loading.value = false }
}

function enterCluster(id: GalaxyClusterId): void { focusCluster.value = id; selectedNodeId.value = null }
function returnOverview(): void { focusCluster.value = null; selectedNodeId.value = null }
function selectNode(node: DigitalTwinNode): void { selectedNodeId.value = node.id }
function selectCore(): void { selectedNodeId.value = twin.value?.nodes.find(node => node.kind === 'household')?.id ?? null }

function startPolling(): void {
  if (pollTimer) clearInterval(pollTimer)
  pollTimer = setInterval(() => { if (document.visibilityState === 'visible') void loadTwin({ silent: true }) }, POLL_INTERVAL_MS)
}

watch(() => session.selectedHouseholdId, () => { returnOverview(); void loadTwin() })
onMounted(() => { void loadTwin(); startPolling(); removeHealthRefreshListener = onHealthDataRefresh(() => void loadTwin({ silent: true })) })
onBeforeUnmount(() => { removeHealthRefreshListener?.(); if (pollTimer) clearInterval(pollTimer); if (deltaTimer) clearTimeout(deltaTimer) })
</script>

<template>
  <section class="page-hero twin-hero">
    <div><p class="eyebrow"><AppIcon name="sparkle" :size="13" /> FAMILY DIGITAL TWIN</p><div class="title-line"><h2 class="hero-greeting gradient-text">家庭数字孪生</h2><span><i /> 本地语义空间</span></div></div>
  </section>
  <p v-if="loadError" class="notice error" role="alert"><AppIcon name="alert" :size="16" /> {{ loadError }}</p>
  <div v-if="loading && !twin" class="inline-loading loading-card"><span class="loading-dots"><span /><span /><span /></span> 正在构建家庭语义星系…</div>
  <section v-else-if="twin" class="twin-galaxy-only">
    <DigitalTwinGalaxy :twin="twin" :focus-cluster="focusCluster" :selected-node-id="selectedNodeId" :recent-node-ids="recentNodeIds" :delta-counts="deltaCounts" :show-unconfirmed="showUnconfirmed" :auto-orbit="autoOrbit" @drill="enterCluster" @back="returnOverview" @select-node="selectNode" @select-core="selectCore" @toggle-unconfirmed="showUnconfirmed = !showUnconfirmed" @toggle-orbit="autoOrbit = !autoOrbit" />
  </section>
</template>

<style scoped>
:global(.view-container.view-digital-twin){max-width:none!important;padding-left:32px!important;padding-right:32px!important}.twin-hero{align-items:flex-end;display:flex;gap:24px;justify-content:space-between;padding-bottom:11px}.eyebrow{align-items:center;color:var(--pine);display:flex;font-size:9px;font-weight:800;gap:5px;letter-spacing:.2em;margin:0 0 5px}.title-line{align-items:center;display:flex;gap:10px}.title-line h2{font-size:28px;margin:0}.title-line>span{align-items:center;background:rgba(229,240,231,.8);border:1px solid rgba(72,119,95,.17);border-radius:999px;color:var(--pine);display:flex;font-size:9px;gap:5px;padding:4px 8px}.title-line i{background:#62a07a;border-radius:50%;height:5px;width:5px}.hero-subtitle{font-size:11px;margin-top:7px}.sync-state{align-items:flex-end;display:flex;flex-direction:column;gap:5px}.sync-state>span{align-items:center;color:var(--pine);display:flex;font-size:9px;gap:5px}.sync-state>span i{background:#6aa180;border-radius:50%;height:6px;width:6px}.sync-state>span i.busy{animation:sync 1s ease-in-out infinite}.sync-state small{color:var(--ink-faint);font-size:8px}.sync-state .btn{font-size:9px;min-height:30px;padding:5px 9px}.truth-banner{margin:0 0 10px;padding:8px 12px}.truth-banner span{font-size:9px}.stats-row{display:grid;gap:9px;grid-template-columns:repeat(5,minmax(0,1fr));margin-bottom:10px}.stats-row article{align-items:center;background:rgba(255,253,248,.82);border:1px solid var(--line-soft);border-radius:13px;display:flex;gap:9px;min-height:58px;padding:9px 11px}.stats-row article>span{align-items:center;background:var(--stat-soft);border-radius:50%;color:var(--stat);display:flex;height:32px;justify-content:center;width:32px}.stats-row div{display:flex;flex-direction:column}.stats-row small{color:var(--ink-faint);font-size:8.5px}.stats-row strong{color:var(--pine-deep);font:700 18px var(--font-numeric);margin-top:2px}.tone-green{--stat:#55906d;--stat-soft:#e4f0e6}.tone-clay{--stat:#ca7650;--stat-soft:#f7e5dc}.tone-blue{--stat:#5d88bd;--stat-soft:#e2ebf6}.tone-purple{--stat:#8468af;--stat-soft:#ece6f5}.tone-teal{--stat:#47958e;--stat-soft:#deefec}.twin-grid{display:grid;gap:11px;grid-template-columns:minmax(0,3fr) minmax(300px,1fr)}.loading-card{background:rgba(255,253,248,.8);border:1px solid var(--line);border-radius:16px;min-height:680px;place-content:center}.twin-footnote{align-items:center;color:var(--ink-faint);display:flex;font-size:8px;justify-content:space-between;padding:9px 3px 2px}.twin-footnote span{align-items:center;display:flex;gap:5px}@keyframes sync{50%{box-shadow:0 0 0 6px rgba(106,161,128,.12);opacity:.45}}@media(max-width:1180px){:global(.view-container.view-digital-twin){padding-left:22px!important;padding-right:22px!important}.twin-grid{grid-template-columns:minmax(0,2.2fr) minmax(280px,.9fr)}}@media(max-width:920px){.twin-grid{grid-template-columns:1fr}.stats-row{grid-template-columns:repeat(3,1fr)}.twin-hero{align-items:flex-start;flex-direction:column}.sync-state{align-items:flex-start}}@media(max-width:620px){.stats-row{grid-template-columns:repeat(2,1fr)}}
.twin-hero{padding-bottom:14px}.twin-galaxy-only{width:100%}.twin-galaxy-only :deep(.galaxy-card){height:calc(100vh - 185px);min-height:660px}.loading-card{min-height:660px}@media(max-width:920px){.twin-galaxy-only :deep(.galaxy-card){height:calc(100vh - 160px);min-height:580px}}
</style>
