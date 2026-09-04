<script setup lang="ts">
defineProps<{ paused: boolean }>()
</script>

<template>
  <div class="galaxy-backdrop" :class="{ paused }" aria-hidden="true">
    <span class="nebula nebula-sage" /><span class="nebula nebula-gold" /><span class="nebula nebula-blue" />
    <svg class="spiral" viewBox="0 0 1200 680" preserveAspectRatio="none">
      <ellipse v-for="index in 7" :key="index" cx="600" cy="352" :rx="120 + index * 74" :ry="38 + index * 35" :class="`ring-${index}`" />
      <path d="M92 392 C245 128 474 246 606 342 C762 456 920 488 1120 260" />
      <path d="M112 180 C330 350 470 438 606 342 C790 210 944 202 1114 414" />
    </svg>
    <span v-for="index in 116" :key="`star-${index}`" class="star" :class="{ large: index % 13 === 0, warm: index % 5 === 0 }" :style="{ left: `${2 + (index * 47) % 96}%`, top: `${3 + (index * 71) % 92}%`, animationDelay: `${-(index % 17) * .31}s`, animationDuration: `${3.2 + (index % 7) * .45}s` }" />
    <span v-for="index in 28" :key="`dust-${index}`" class="dust" :style="{ left: `${5 + (index * 37) % 90}%`, top: `${8 + (index * 53) % 84}%`, animationDelay: `${-(index % 9) * .8}s`, '--dust-size': `${3 + index % 4}px` }" />
    <span v-for="index in 5" :key="`comet-${index}`" class="comet" :style="{ left: `${8 + index * 19}%`, top: `${16 + (index * 23) % 62}%`, animationDelay: `${-index * 3.2}s` }" />
  </div>
</template>

<style scoped>
.galaxy-backdrop{inset:0;overflow:hidden;pointer-events:none;position:absolute}.nebula{border-radius:50%;filter:blur(28px);opacity:.32;position:absolute;animation:nebula 18s ease-in-out infinite}.nebula-sage{background:radial-gradient(circle,rgba(107,153,125,.19),transparent 70%);height:64%;left:8%;top:14%;width:54%}.nebula-gold{animation-delay:-7s;background:radial-gradient(circle,rgba(208,164,86,.18),transparent 70%);height:58%;right:4%;top:5%;width:48%}.nebula-blue{animation-delay:-12s;background:radial-gradient(circle,rgba(102,143,182,.13),transparent 72%);bottom:-10%;height:52%;left:34%;width:48%}.spiral{height:100%;inset:0;overflow:visible;position:absolute;width:100%}.spiral ellipse,.spiral path{fill:none;stroke:rgba(185,148,86,.18);stroke-width:1}.spiral ellipse:nth-child(even){stroke:rgba(87,133,110,.14);stroke-dasharray:3 7}.spiral ellipse{transform-box:fill-box;transform-origin:center;animation:spin 42s linear infinite}.spiral ellipse:nth-child(3n){animation-direction:reverse;animation-duration:55s}.spiral path{stroke-dasharray:2 8;stroke-width:.8}.star{animation:twinkle 4s ease-in-out infinite;background:rgba(255,255,255,.92);border-radius:50%;box-shadow:0 0 6px rgba(255,255,255,.9);height:2px;opacity:.48;position:absolute;width:2px}.star.large{height:5px;width:5px}.star.large::after,.star.large::before{background:rgba(255,255,255,.8);content:"";left:50%;position:absolute;top:50%;transform:translate(-50%,-50%)}.star.large::before{height:1px;width:16px}.star.large::after{height:16px;width:1px}.star.warm{background:#e7c786;box-shadow:0 0 8px rgba(205,158,73,.55)}.dust{--dust-size:4px;animation:drift 9s ease-in-out infinite;background:radial-gradient(circle at 30% 25%,white,#91ad9a 62%,#5f806d);border-radius:50%;box-shadow:0 0 7px rgba(81,125,102,.25);height:var(--dust-size);opacity:.42;position:absolute;width:var(--dust-size)}.dust:nth-of-type(3n){background:radial-gradient(circle at 30% 25%,white,#e0bc73 62%,#aa7730)}.comet{animation:comet 17s linear infinite;background:linear-gradient(90deg,transparent,rgba(221,185,116,.16),rgba(255,255,255,.85));border-radius:999px;height:1px;opacity:0;position:absolute;transform:rotate(-18deg);width:78px}.paused *{animation-play-state:paused!important}@keyframes spin{to{transform:rotate(360deg)}}@keyframes twinkle{50%{opacity:1;transform:scale(1.45)}}@keyframes drift{50%{opacity:.75;transform:translate3d(9px,-12px,0) scale(1.2)}}@keyframes comet{0%,67%{opacity:0;transform:translate(-90px,30px) rotate(-18deg)}72%{opacity:.7}88%,100%{opacity:0;transform:translate(220px,-64px) rotate(-18deg)}}@keyframes nebula{50%{opacity:.46;transform:scale(1.08) translate(2%,-2%)}}@media(prefers-reduced-motion:reduce){.galaxy-backdrop *{animation:none!important}}
</style>
