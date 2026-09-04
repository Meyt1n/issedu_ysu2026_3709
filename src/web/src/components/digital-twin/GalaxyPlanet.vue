<script setup lang="ts">
import type { GalaxyCluster } from '../../digital-twin/galaxy-types'
import AppIcon from '../AppIcon.vue'

defineProps<{ cluster: GalaxyCluster; count: number; delta: number; subdued?: boolean }>()
defineEmits<{ open: [] }>()
</script>

<template>
  <button class="planet-system" :class="{ updated: delta > 0, subdued }" type="button" :style="{ '--tone': cluster.color, '--soft': cluster.soft, left: `${cluster.x}%`, top: `${cluster.y}%` }" :aria-label="`进入${cluster.label}局部星系`" @click="$emit('open')">
    <span class="orbit orbit-one"><i /><i /></span>
    <span class="orbit orbit-two"><i /><i /><i /></span>
    <span class="orbit orbit-three" />
    <span class="planet">
      <span class="shine" />
      <AppIcon :name="cluster.icon" :size="27" />
      <strong>{{ cluster.shortLabel }}</strong>
      <small>{{ count }} 个节点</small>
    </span>
    <em v-if="delta">+{{ delta }}</em>
  </button>
</template>

<style scoped>
.planet-system{--tone:#5d9a76;--soft:#e4f0e6;background:none;border:0;cursor:pointer;height:190px;padding:0;position:absolute;transform:translate(-50%,-50%) translateZ(34px);transition:filter .5s ease,opacity .5s ease,transform .5s ease;width:250px;z-index:30}.planet-system:hover{transform:translate(-50%,-50%) translateZ(50px) scale(1.04)}.planet{align-items:center;background:radial-gradient(circle at 31% 20%,rgba(255,255,255,.99) 0 9%,color-mix(in srgb,var(--soft) 78%,white) 34%,color-mix(in srgb,var(--tone) 76%,#35453e) 100%);border:1px solid rgba(255,255,255,.88);border-radius:50%;box-shadow:0 18px 33px color-mix(in srgb,var(--tone) 28%,transparent),inset -7px -10px 18px color-mix(in srgb,var(--tone) 20%,transparent),inset 4px 5px 13px rgba(255,255,255,.94),0 0 0 7px rgba(255,255,255,.2);color:color-mix(in srgb,var(--tone) 78%,#26372f);display:flex;flex-direction:column;height:104px;justify-content:center;left:50%;overflow:hidden;position:absolute;top:50%;transform:translate(-50%,-50%);width:104px;z-index:4}.planet::after{background:linear-gradient(110deg,transparent 25%,rgba(255,255,255,.58) 46%,transparent 62%);content:"";inset:-20%;position:absolute;transform:translateX(-55%) rotate(-8deg);transition:transform .65s ease}.planet-system:hover .planet::after{transform:translateX(55%) rotate(-8deg)}.planet>*{position:relative;z-index:2}.planet strong{font-family:var(--font-display);font-size:13px;margin-top:5px}.planet small{font-size:8px;margin-top:2px;opacity:.72}.shine{background:rgba(255,255,255,.92);border-radius:50%;filter:blur(2px);height:11px;left:21px;position:absolute;top:14px;width:25px}.orbit{border:1px solid color-mix(in srgb,var(--tone) 35%,transparent);border-radius:50%;left:50%;position:absolute;top:50%;transform:translate(-50%,-50%) rotateX(68deg)}.orbit-one{animation:orbit 13s linear infinite;height:128px;width:230px}.orbit-two{animation:orbit 18s linear infinite reverse;border-style:dashed;height:158px;width:196px}.orbit-three{height:103px;opacity:.45;width:254px}.orbit i{background:radial-gradient(circle at 30% 25%,white,var(--tone));border:1px solid rgba(255,255,255,.8);border-radius:50%;box-shadow:0 0 10px color-mix(in srgb,var(--tone) 48%,transparent);height:8px;left:9%;position:absolute;top:47%;width:8px}.orbit i:nth-child(2){left:auto;right:13%;top:64%}.orbit i:nth-child(3){left:55%;top:-3px}.planet-system em{background:rgba(255,253,248,.94);border:1px solid color-mix(in srgb,var(--tone) 35%,var(--line));border-radius:999px;color:var(--tone);font-size:10px;font-style:normal;font-weight:800;padding:4px 8px;position:absolute;right:24px;top:22px}.updated .planet{animation:pulse 1.45s ease-in-out 3}.subdued{filter:blur(1px);opacity:.16;pointer-events:none}@keyframes orbit{to{transform:translate(-50%,-50%) rotateX(68deg) rotateZ(360deg)}}@keyframes pulse{50%{box-shadow:0 20px 42px color-mix(in srgb,var(--tone) 44%,transparent),0 0 0 13px color-mix(in srgb,var(--tone) 12%,transparent)}}@media(max-width:1180px){.planet-system{transform:translate(-50%,-50%) translateZ(34px) scale(.88)}}@media(prefers-reduced-motion:reduce){.planet-system *{animation:none!important}}
</style>
