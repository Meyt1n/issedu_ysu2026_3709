<script setup lang="ts">
import { computed, ref } from 'vue'

import type { DigitalTwinNode, DigitalTwinResponse } from '../../api/types'
import { buildGlobalOrbitNodes, buildLocalOrbitNodes, countByCluster, GALAXY_CLUSTERS, visibleTwinNodes } from '../../digital-twin/galaxy-layout'
import type { GalaxyCluster, GalaxyClusterId, GalaxyOrbitNode } from '../../digital-twin/galaxy-types'
import AppIcon from '../AppIcon.vue'

const props = defineProps<{
  twin: DigitalTwinResponse
  focusCluster: GalaxyClusterId | null
  selectedNodeId: string | null
  recentNodeIds: Set<string>
  deltaCounts: Record<GalaxyClusterId, number>
  showUnconfirmed: boolean
  autoOrbit: boolean
}>()

const emit = defineEmits<{
  drill: [clusterId: GalaxyClusterId]
  back: []
  selectNode: [node: DigitalTwinNode]
  selectCore: []
  toggleUnconfirmed: []
  toggleOrbit: []
}>()

const stage = ref<HTMLElement | null>(null)
const tiltX = ref(0)
const tiltY = ref(0)
const spatial = ref(true)

const nodes = computed(() => visibleTwinNodes(props.twin, props.showUnconfirmed))
const counts = computed(() => countByCluster(nodes.value))
const focus = computed(() => GALAXY_CLUSTERS.find(item => item.id === props.focusCluster) ?? null)
const orbitNodes = computed(() => focus.value
  ? buildLocalOrbitNodes(nodes.value, focus.value.id)
  : GALAXY_CLUSTERS.flatMap(cluster => buildGlobalOrbitNodes(nodes.value, cluster)))

function clusterStyle(cluster: GalaxyCluster): Record<string, string> {
  return { '--cluster-color': cluster.color, '--cluster-soft': cluster.soft, left: `${cluster.x}%`, top: `${cluster.y}%` }
}

function orbitNodeStyle(item: GalaxyOrbitNode): Record<string, string> {
  const cluster = GALAXY_CLUSTERS.find(candidate => candidate.id === item.clusterId)!
  return { '--cluster-color': cluster.color, '--cluster-soft': cluster.soft, '--depth': `${Math.round(item.z * 45)}px`, left: `${item.x}%`, top: `${item.y}%`, zIndex: String(item.ring === 1 ? 42 : 25) }
}

function onPointerMove(event: PointerEvent): void {
  if (!spatial.value || !stage.value) return
  const bounds = stage.value.getBoundingClientRect()
  tiltY.value = ((event.clientX - bounds.left) / bounds.width - .5) * 5
  tiltX.value = (.5 - (event.clientY - bounds.top) / bounds.height) * 3.5
}

function resetTilt(): void { tiltX.value = 0; tiltY.value = 0 }
function truncate(value: string, max = 16): string { return value.length > max ? `${value.slice(0, max)}…` : value }
</script>

<template>
  <section ref="stage" class="galaxy-card card" :class="{ 'is-paused': !autoOrbit, 'is-flat': !spatial }" @pointermove="onPointerMove" @pointerleave="resetTilt">
    <header class="galaxy-toolbar">
      <div class="galaxy-path">
        <button v-if="focus" type="button" @click="emit('back')"><AppIcon name="rewind" :size="13" /> 家庭语义空间</button>
        <span v-else><i /> 家庭语义空间</span>
        <template v-if="focus"><b>/</b><strong>{{ focus.label }}局部星系</strong></template>
      </div>
      <div class="galaxy-controls">
        <label><input :checked="showUnconfirmed" type="checkbox" @change="emit('toggleUnconfirmed')" /> 未确认线索</label>
        <div><button type="button" :class="{ active: spatial }" @click="spatial = true">2.5D</button><button type="button" :class="{ active: !spatial }" @click="spatial = false">平面</button></div>
        <button type="button" class="motion-button" @click="emit('toggleOrbit')"><AppIcon :name="autoOrbit ? 'pause' : 'play'" :size="11" /> {{ autoOrbit ? '暂停' : '流动' }}</button>
      </div>
    </header>

    <div class="galaxy-viewport" :style="{ '--tilt-x': `${tiltX}deg`, '--tilt-y': `${tiltY}deg` }">
      <Transition name="galaxy-shift" mode="out-in">
        <div :key="focus?.id ?? 'overview'" class="galaxy-world">
          <div class="galaxy-floor"><i /><i /><i /></div>
          <div class="galaxy-atmosphere" aria-hidden="true">
            <i class="galaxy-nebula nebula-a" /><i class="galaxy-nebula nebula-b" /><i class="galaxy-nebula nebula-c" /><i class="galaxy-nebula nebula-d" />
            <span v-for="index in 72" :key="`star-${index}`" class="galaxy-star" :style="{ left: `${4 + (index * 37) % 92}%`, top: `${5 + (index * 53) % 88}%`, animationDelay: `${-(index % 12) * .45}s`, '--star-size': `${1 + (index % 3)}px` }" />
            <span v-for="index in 14" :key="`flare-${index}`" class="galaxy-flare" :style="{ left: `${9 + (index * 43) % 82}%`, top: `${11 + (index * 29) % 76}%`, animationDelay: `${-(index % 7) * .8}s`, '--flare-size': `${4 + (index % 3)}px` }" />
          </div>
          <svg class="galaxy-links" viewBox="0 0 100 100" preserveAspectRatio="none" aria-hidden="true">
            <template v-if="!focus">
              <path v-for="cluster in GALAXY_CLUSTERS" :key="cluster.id" :d="`M 50 50 Q 50 ${cluster.y} ${cluster.x} ${cluster.y}`" />
            </template>
            <template v-else>
              <line v-for="node in orbitNodes" :key="node.id" x1="50" y1="52" :x2="node.x" :y2="node.y" :class="{ recent: node.node && recentNodeIds.has(node.node.id) }" />
            </template>
          </svg>

          <span v-for="index in 96" :key="index" class="galaxy-particle" :class="`particle-${index % 4}`" :style="{ left: `${3 + (index * 31) % 94}%`, top: `${4 + (index * 47) % 90}%`, animationDelay: `${-(index % 11) * .62}s`, '--particle-size': `${4 + (index % 4)}px` }" />
          <span v-for="index in 7" :key="`comet-${index}`" class="galaxy-comet" :class="`comet-${index}`" :style="{ left: `${12 + index * 13}%`, top: `${17 + (index * 19) % 64}%`, animationDelay: `${-(index * 2.8)}s` }" />

          <template v-if="!focus">
            <button v-for="cluster in GALAXY_CLUSTERS" :key="cluster.id" type="button" class="cluster-system" :class="{ updated: deltaCounts[cluster.id] > 0 }" :style="clusterStyle(cluster)" @click="emit('drill', cluster.id)">
              <span class="system-orbit orbit-a" /><span class="system-orbit orbit-b" />
              <span class="cluster-sphere"><AppIcon :name="cluster.icon" :size="23" /><strong>{{ cluster.shortLabel }}</strong><small>{{ counts[cluster.id] }} 个节点</small></span>
              <em v-if="deltaCounts[cluster.id]">+{{ deltaCounts[cluster.id] }}</em>
            </button>
          </template>

          <button v-for="item in orbitNodes" :key="item.id" type="button" class="orbit-node" :class="{ guide: item.guide, selected: item.node?.id === selectedNodeId, recent: item.node && recentNodeIds.has(item.node.id), local: !!focus }" :style="orbitNodeStyle(item)" :disabled="item.guide" @click="item.node && emit('selectNode', item.node)">
            <i /><span>{{ truncate(item.label, focus ? 22 : 13) }}</span><small v-if="item.node?.status === 'UNCONFIRMED'">待确认</small>
          </button>

          <button type="button" class="galaxy-core" :style="focus ? { '--cluster-color': focus.color, '--cluster-soft': focus.soft } : undefined" @click="focus ? undefined : emit('selectCore')">
            <span class="core-ring ring-a" /><span class="core-ring ring-b" />
            <span class="core-sphere"><AppIcon :name="focus?.icon ?? 'home'" :size="30" /><strong>{{ focus?.shortLabel ?? '家庭语义核心' }}</strong><small v-if="focus">{{ counts[focus.id] }} 个真实节点 · 点击词项查看证据</small><small v-else>{{ twin.stats.member_count }} 位成员 · {{ twin.nodes.length }} 个节点</small></span>
          </button>

          <div v-if="focus && !nodes.some(node => node && node.id && node.kind !== 'household' && node.category && orbitNodes.some(item => item.node?.id === node.id))" class="empty-hint">当前类别暂无真实记录，淡色节点仅表示可接入的数据维度。</div>
        </div>
      </Transition>
    </div>

    <footer class="galaxy-footer">
      <span><i class="real-dot" /> 真实记录</span><span><i class="guide-dot" /> 可接入维度</span><span><i class="relation-line" /> 本地真实关系</span>
      <small>{{ focus ? '点击节点查看来源；使用面包屑返回总览' : '点击类别球进入局部语义星系' }}</small>
    </footer>
  </section>
</template>

<style scoped>
.galaxy-card{--card-pattern:none;background:radial-gradient(circle at 50% 45%,rgba(244,249,242,.9),rgba(255,253,248,.9) 48%,rgba(246,241,231,.92));height:680px;min-width:0;overflow:hidden;padding:0;position:relative}.galaxy-toolbar{align-items:center;border-bottom:1px solid rgba(111,102,83,.09);display:flex;justify-content:space-between;padding:13px 16px;position:relative;z-index:90}.galaxy-path{align-items:center;display:flex;gap:8px}.galaxy-path span,.galaxy-path button{align-items:center;background:none;border:0;color:var(--pine-deep);display:flex;font-size:12px;font-weight:700;gap:6px;padding:0}.galaxy-path span i{animation:live 1.8s ease-in-out infinite;background:#66a27d;border-radius:50%;box-shadow:0 0 0 4px rgba(102,162,125,.11);height:6px;width:6px}.galaxy-path b{color:var(--line);font-weight:400}.galaxy-path strong{color:var(--clay-deep);font-size:11px}.galaxy-controls{align-items:center;display:flex;gap:8px}.galaxy-controls label{align-items:center;color:var(--ink-faint);display:flex;font-size:9px;gap:4px}.galaxy-controls input{accent-color:var(--pine)}.galaxy-controls>div{background:rgba(238,234,225,.75);border-radius:999px;padding:2px}.galaxy-controls button{background:transparent;border:0;border-radius:999px;color:var(--ink-faint);font-size:9px;padding:4px 7px}.galaxy-controls button.active{background:white;box-shadow:0 2px 7px rgba(57,68,56,.1);color:var(--pine-deep)}.motion-button{align-items:center!important;border:1px solid var(--line)!important;display:flex!important;gap:4px!important}.galaxy-viewport{inset:49px 0 39px;overflow:hidden;perspective:1100px;position:absolute}.galaxy-world{height:100%;position:relative;transform:rotateX(var(--tilt-x)) rotateY(var(--tilt-y));transform-style:preserve-3d;transition:transform .2s ease;width:100%}.is-flat .galaxy-world{transform:none}.galaxy-floor{height:75%;left:50%;position:absolute;top:52%;transform:translate(-50%,-50%) rotateX(74deg) translateZ(-100px);width:86%}.galaxy-floor i{border:1px solid rgba(67,116,93,.11);border-radius:50%;inset:0;position:absolute}.galaxy-floor i:nth-child(2){inset:17%}.galaxy-floor i:nth-child(3){border-color:rgba(200,150,72,.14);inset:34%}.galaxy-links{height:100%;inset:0;pointer-events:none;position:absolute;width:100%;z-index:4}.galaxy-links path,.galaxy-links line{animation:dash 9s linear infinite;fill:none;stroke:rgba(83,126,106,.34);stroke-dasharray:1.2 1.3;stroke-width:.22}.galaxy-links line.recent{filter:drop-shadow(0 0 3px #78a887);stroke:#72a587;stroke-width:.45}.galaxy-particle{animation:float 7s ease-in-out infinite;background:radial-gradient(circle at 30% 25%,#fff,#79a28e 60%,#547665);border-radius:50%;box-shadow:0 0 7px rgba(75,125,101,.25);height:4px;opacity:.35;position:absolute;width:4px;z-index:6}.galaxy-particle:nth-child(3n){background:radial-gradient(circle at 30% 25%,#fff,#d7aa63 60%,#b27b32)}.cluster-system{--cluster-color:#5d9a76;--cluster-soft:#e4f0e6;background:transparent;border:0;cursor:pointer;height:170px;padding:0;position:absolute;transform:translate(-50%,-50%) translateZ(35px);width:210px;z-index:30}.cluster-sphere,.core-sphere{align-items:center;background:radial-gradient(circle at 32% 22%,rgba(255,255,255,.98),color-mix(in srgb,var(--cluster-soft) 85%,white) 32%,color-mix(in srgb,var(--cluster-color) 80%,#33483f) 100%);border:1px solid rgba(255,255,255,.82);border-radius:50%;box-shadow:0 18px 27px color-mix(in srgb,var(--cluster-color) 24%,transparent),inset 0 2px 5px rgba(255,255,255,.9),inset 0 -10px 18px color-mix(in srgb,var(--cluster-color) 22%,transparent);color:color-mix(in srgb,var(--cluster-color) 75%,#243b32);display:flex;flex-direction:column;height:82px;justify-content:center;left:50%;position:absolute;top:50%;transform:translate(-50%,-50%);transition:transform .22s ease;width:82px;z-index:4}.cluster-system:hover .cluster-sphere{transform:translate(-50%,-50%) scale(1.08)}.cluster-sphere strong{font-family:var(--font-display);font-size:11px;margin-top:3px}.cluster-sphere small{font-size:7px;margin-top:2px;opacity:.72}.system-orbit,.core-ring{border:1px solid color-mix(in srgb,var(--cluster-color) 30%,transparent);border-radius:50%;left:50%;position:absolute;top:50%;transform:translate(-50%,-50%) rotateX(68deg)}.system-orbit.orbit-a{animation:orbit 13s linear infinite;height:145px;width:205px}.system-orbit.orbit-b{animation:orbit 18s linear infinite reverse;border-style:dashed;height:110px;width:175px}.cluster-system em{background:#fff;border:1px solid color-mix(in srgb,var(--cluster-color) 30%,var(--line));border-radius:999px;color:var(--cluster-color);font-size:9px;font-style:normal;font-weight:800;padding:3px 6px;position:absolute;right:25px;top:23px}.cluster-system.updated .cluster-sphere{animation:pulse 1.45s ease-in-out 3}.orbit-node{--cluster-color:#5d9a76;--cluster-soft:#e4f0e6;--depth:0;align-items:center;background:linear-gradient(145deg,rgba(255,255,255,.91),color-mix(in srgb,var(--cluster-soft) 80%,white));border:1px solid color-mix(in srgb,var(--cluster-color) 28%,var(--line));border-radius:999px;box-shadow:0 8px 16px color-mix(in srgb,var(--cluster-color) 13%,transparent);color:color-mix(in srgb,var(--cluster-color) 76%,#273a32);display:flex;gap:5px;max-width:160px;padding:6px 10px;position:absolute;transform:translate(-50%,-50%) translateZ(var(--depth));transition:all .2s ease;white-space:nowrap}.orbit-node i{background:radial-gradient(circle at 30% 25%,#fff,var(--cluster-color));border-radius:50%;height:6px;width:6px}.orbit-node span{font-size:9.5px;font-weight:650;overflow:hidden;text-overflow:ellipsis}.orbit-node small{background:rgba(255,255,255,.65);border-radius:999px;color:#a06c24;font-size:7px;padding:1px 4px}.orbit-node:hover,.orbit-node.selected{box-shadow:0 11px 23px color-mix(in srgb,var(--cluster-color) 24%,transparent),0 0 0 3px color-mix(in srgb,var(--cluster-color) 12%,transparent);transform:translate(-50%,-50%) translateZ(calc(var(--depth) + 12px)) scale(1.05)}.orbit-node.guide{border-style:dashed;box-shadow:none;cursor:default;opacity:.58}.orbit-node.recent{animation:node-in .65s both,pulse 1.5s .7s 2}.galaxy-core{--cluster-color:#416f5d;--cluster-soft:#dce9df;background:transparent;border:0;height:230px;left:50%;padding:0;position:absolute;top:50%;transform:translate(-50%,-50%) translateZ(80px);width:270px;z-index:50}.core-sphere{background:radial-gradient(circle at 32% 23%,rgba(255,255,255,.96),color-mix(in srgb,var(--cluster-color) 66%,#547566) 34%,color-mix(in srgb,var(--cluster-color) 82%,#1f4436) 72%,#244b3d);box-shadow:0 25px 42px color-mix(in srgb,var(--cluster-color) 32%,transparent),inset 0 3px 5px rgba(255,255,255,.68),inset 0 -15px 24px rgba(18,51,39,.25);color:#fffaf2;height:126px;text-shadow:0 1px 4px rgba(20,53,41,.35);width:126px}.core-sphere strong{font-family:var(--font-display);font-size:16px;margin-top:5px}.core-sphere small{font-size:8px;line-height:1.4;margin-top:3px;max-width:102px;opacity:.76}.core-ring.ring-a{animation:orbit 15s linear infinite;height:195px;width:265px}.core-ring.ring-b{animation:orbit 10s linear infinite reverse;border-color:rgba(197,147,74,.4);border-style:dashed;height:150px;width:220px}.empty-hint{background:rgba(255,250,238,.9);border:1px solid var(--line);border-radius:999px;bottom:18px;color:var(--gold-ink);font-size:9px;left:50%;padding:5px 9px;position:absolute;transform:translateX(-50%);z-index:75}.galaxy-footer{align-items:center;bottom:0;display:flex;gap:12px;left:0;padding:11px 16px;position:absolute;right:0;z-index:90}.galaxy-footer span{align-items:center;color:var(--ink-faint);display:flex;font-size:8.5px;gap:4px}.galaxy-footer i{display:inline-block}.real-dot{background:var(--pine);border-radius:50%;height:6px;width:6px}.guide-dot{border:1px dashed var(--sage);border-radius:50%;height:6px;width:6px}.relation-line{border-top:1px dashed var(--sky);width:12px}.galaxy-footer small{color:var(--ink-faint);font-size:8.5px;margin-left:auto}.is-paused :is(.system-orbit,.core-ring,.galaxy-particle,.galaxy-links path,.galaxy-links line){animation-play-state:paused}.galaxy-shift-enter-active,.galaxy-shift-leave-active{transition:opacity .25s ease,transform .32s ease}.galaxy-shift-enter-from{opacity:0;transform:scale(.9)}.galaxy-shift-leave-to{opacity:0;transform:scale(1.08)}@keyframes orbit{to{transform:translate(-50%,-50%) rotateX(68deg) rotateZ(360deg)}}@keyframes dash{to{stroke-dashoffset:-18}}@keyframes float{50%{opacity:.75;transform:translate3d(4px,-8px,35px) scale(1.18)}}@keyframes live{50%{opacity:.45;box-shadow:0 0 0 7px rgba(102,162,125,.05)}}@keyframes pulse{50%{filter:saturate(1.16);box-shadow:0 20px 36px color-mix(in srgb,var(--cluster-color) 34%,transparent),0 0 0 10px color-mix(in srgb,var(--cluster-color) 10%,transparent)}}@keyframes node-in{from{opacity:0;transform:translate(-50%,-50%) scale(.35)}}@media(max-width:1180px){.galaxy-card{height:620px}.cluster-system{transform:translate(-50%,-50%) scale(.88)}.orbit-node{max-width:125px}.orbit-node span{font-size:8.5px}}@media(prefers-reduced-motion:reduce){.galaxy-card *{animation:none!important;transition:none!important}}
.galaxy-core{height:126px;width:126px}.galaxy-core .core-ring{pointer-events:none}

/* 节点整体放大：提升 16:9 桌面视图的可读性，同时保留轨道层次。 */
.cluster-system{height:190px;width:230px}
.cluster-sphere{height:96px;width:96px}
.cluster-sphere strong{font-size:12px}
.cluster-sphere small{font-size:8px}
.system-orbit.orbit-a{height:166px;width:235px}
.system-orbit.orbit-b{height:126px;width:200px}
.cluster-system em{font-size:10px;padding:4px 7px}
.galaxy-particle{height:5px;width:5px}
.orbit-node{max-width:180px;padding:7px 11px}
.orbit-node i{height:7px;width:7px}
.orbit-node span{font-size:10.5px}
.orbit-node small{font-size:8px}
.core-sphere{height:144px;width:144px}
.core-sphere strong{font-size:17px}
.core-sphere small{font-size:8.5px;max-width:118px}
.galaxy-core{height:148px;width:148px}
.core-ring.ring-a{height:220px;width:300px}
.core-ring.ring-b{height:170px;width:250px}
@media(max-width:1180px){.cluster-system{transform:translate(-50%,-50%) scale(.92)}.orbit-node{max-width:155px;padding:7px 10px}.orbit-node span{font-size:10px}}

/* 星系氛围层：低对比度星云、闪烁星点与少量彗星轨迹，避免抢过语义节点。 */
.galaxy-atmosphere{inset:0;pointer-events:none;position:absolute;z-index:1}
.galaxy-nebula{border-radius:50%;filter:blur(14px);opacity:.3;position:absolute;transform-origin:center;animation:nebula-drift 18s ease-in-out infinite}
.nebula-a{background:radial-gradient(circle,color-mix(in srgb,var(--pine) 17%,transparent),transparent 68%);height:48%;left:0;top:8%;width:43%}
.nebula-b{animation-delay:-6s;background:radial-gradient(circle,color-mix(in srgb,var(--clay) 16%,transparent),transparent 70%);height:42%;right:1%;top:15%;width:39%}
.nebula-c{animation-delay:-11s;background:radial-gradient(circle,color-mix(in srgb,var(--sky) 18%,transparent),transparent 72%);bottom:0;height:38%;left:30%;width:42%}
.galaxy-star{--star-size:2px;animation:twinkle 3.6s ease-in-out infinite;background:rgba(255,255,255,.92);border-radius:50%;box-shadow:0 0 5px rgba(255,255,255,.7),0 0 9px color-mix(in srgb,var(--sage) 42%,transparent);height:var(--star-size);opacity:.36;position:absolute;width:var(--star-size);z-index:3}
.galaxy-star:nth-child(4n){background:color-mix(in srgb,var(--gold) 72%,white);box-shadow:0 0 6px color-mix(in srgb,var(--gold) 50%,transparent)}
.galaxy-star:nth-child(5n){animation-duration:5.2s;opacity:.24}
.galaxy-particle.particle-0{box-shadow:0 0 9px color-mix(in srgb,var(--pine) 45%,transparent)}
.galaxy-particle.particle-1{animation-duration:9s;background:radial-gradient(circle at 30% 25%,#fff,#d5a762 60%,#b27b32);box-shadow:0 0 9px color-mix(in srgb,var(--gold) 42%,transparent)}
.galaxy-particle.particle-2{animation-duration:6s;opacity:.25}
.galaxy-particle.particle-3{animation-duration:11s;background:radial-gradient(circle at 30% 25%,#fff,#75aaa5 60%,#3e817c);box-shadow:0 0 9px color-mix(in srgb,var(--sky) 42%,transparent)}
.galaxy-comet{animation:comet-pass 13s linear infinite;background:linear-gradient(90deg,transparent,color-mix(in srgb,var(--sky) 38%,transparent),rgba(255,255,255,.82));border-radius:999px;filter:blur(.15px);height:2px;opacity:0;position:absolute;transform:rotate(-22deg);width:82px;z-index:7}
.galaxy-comet::after{background:radial-gradient(ellipse,rgba(255,255,255,.9),transparent 70%);border-radius:50%;content:'';height:8px;position:absolute;right:-2px;top:-3px;width:8px}
.comet-2,.comet-5{animation-delay:-4s;background:linear-gradient(90deg,transparent,color-mix(in srgb,var(--gold) 38%,transparent),rgba(255,255,255,.8));transform:rotate(18deg)}
.comet-3{animation-delay:-8s;transform:rotate(-8deg)}
@keyframes nebula-drift{0%,100%{opacity:.2;transform:translate3d(0,0,0) scale(.96)}50%{opacity:.38;transform:translate3d(12px,-8px,0) scale(1.04)}}
@keyframes twinkle{0%,100%{opacity:.18;transform:scale(.75)}50%{opacity:.78;transform:scale(1.35)}}
@keyframes comet-pass{0%,8%{opacity:0;transform:translate3d(-45px,28px,0) rotate(-22deg)}18%{opacity:.58}58%{opacity:.16}78%,100%{opacity:0;transform:translate3d(105px,-65px,0) rotate(-22deg)}}
@media(prefers-reduced-motion:reduce){.galaxy-atmosphere *{animation:none!important}}
.nebula-d{animation-delay:-15s;background:radial-gradient(circle,color-mix(in srgb,var(--gold) 13%,transparent),transparent 70%);bottom:4%;height:30%;left:4%;width:33%}
.galaxy-star:nth-child(7n){animation-duration:6.2s;opacity:.5}
.galaxy-flare{--flare-size:5px;animation:flare-pulse 4.8s ease-in-out infinite;background:radial-gradient(circle,rgba(255,255,255,.95) 0 18%,color-mix(in srgb,var(--gold) 70%,white) 35%,transparent 72%);border-radius:50%;height:var(--flare-size);opacity:.56;position:absolute;width:var(--flare-size);z-index:4}
.galaxy-flare::before,.galaxy-flare::after{background:linear-gradient(transparent,color-mix(in srgb,var(--gold) 52%,white),transparent);content:'';inset:-5px 42%;position:absolute}
.galaxy-flare::after{background:linear-gradient(90deg,transparent,color-mix(in srgb,var(--gold) 52%,white),transparent);inset:42% -5px}
.galaxy-particle{height:var(--particle-size,5px);opacity:.45;width:var(--particle-size,5px)}
@keyframes flare-pulse{0%,100%{filter:blur(.2px);opacity:.2;transform:scale(.72)}50%{filter:blur(0);opacity:.72;transform:scale(1.28)}}
</style>
