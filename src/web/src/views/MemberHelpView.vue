<script setup lang="ts">
import { computed } from 'vue'

import AppIcon from '../components/AppIcon.vue'
import { selectedMember, setView, signOut } from '../store'

const memberName = computed(() => selectedMember.value?.display_name ?? '家人')
</script>

<template>
  <section class="page-hero member-portal-hero">
    <p class="eyebrow">使用帮助</p>
    <h2 class="hero-greeting">有问题先看这里</h2>
    <p class="hero-sub">怎么拍照、怎么看记录，以及信息保存在哪里。</p>
  </section>

  <section class="card member-help-card">
    <h3 class="card-title">拍照录药怎么做？</h3>
    <ol class="member-help-steps">
      <li>进入「拍照录药」，把药盒正面放在光线好的地方。</li>
      <li>按提示看看照片清不清楚，然后交给家人确认。</li>
      <li>提交后会显示「正在看照片」或「等待家人确认」，不会马上记进家庭本子。</li>
      <li>家人确认后，你可以在「我的记录」和「服药提醒」里看到结果。</li>
    </ol>
    <button type="button" class="btn btn-clay" @click="setView('member-capture')">
      <AppIcon name="scan" :size="16" />
      去拍照录药
    </button>
  </section>

  <section class="card member-help-card">
    <h3 class="card-title">信息保存在哪里？</h3>
    <p class="member-help-text">
      {{ memberName }}，你的健康信息默认保存在家里的电脑或小盒子里，不会自动上网。
      只有家人确认过的内容，才会出现在你的记录里。
    </p>
  </section>

  <section class="card member-help-card member-help-emergency">
    <h3 class="card-title">遇到紧急情况怎么办？</h3>
    <p class="member-help-text">
      本系统只做家庭记录和提醒参考，<strong>不能代替医生诊断</strong>。
      如果出现胸痛、呼吸困难、意识不清等紧急情况，请立即联系当地急救电话或家人。
    </p>
  </section>

  <section class="card member-help-card">
    <h3 class="card-title">当前登录</h3>
    <p class="member-help-text">你现在使用的是 {{ memberName }} 的家庭成员账号。</p>
    <button type="button" class="btn btn-ghost" @click="signOut">
      <AppIcon name="signout" :size="16" />
      退出登录
    </button>
  </section>
</template>
