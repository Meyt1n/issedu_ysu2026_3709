<script setup lang="ts">
import { computed } from 'vue'

import AppIcon from '../components/AppIcon.vue'
import { selectedMember, session, setView, signOut } from '../store'

const memberName = computed(() => selectedMember.value?.display_name ?? '家人')
</script>

<template>
  <section class="page-hero member-portal-hero">
    <p class="eyebrow">使用帮助</p>
    <h2 class="hero-greeting">有问题先看这里</h2>
    <p class="hero-sub">这里用最简单的话说明怎么拍照、怎么看记录，以及数据保存在哪里。</p>
  </section>

  <section class="card member-help-card">
    <h3 class="card-title">拍照录药怎么做？</h3>
    <ol class="member-help-steps">
      <li>进入「拍照录药」，把药盒正面放在光线好的地方。</li>
      <li>按提示检查照片是否清楚，然后提交给家庭管理员。</li>
      <li>提交后照片会显示「正在识别」或「等待家人确认」，不会直接写进健康记录。</li>
      <li>管理员确认后，你可以在「我的记录」和「服药提醒」里看到结果。</li>
    </ol>
    <button type="button" class="btn btn-clay" @click="setView('member-capture')">
      <AppIcon name="scan" :size="16" />
      去拍照录药
    </button>
  </section>

  <section class="card member-help-card">
    <h3 class="card-title">数据保存在哪里？</h3>
    <p class="member-help-text">
      {{ memberName }}，你的健康信息默认保存在本机家庭服务器里，不会自动上传到互联网。
      只有家庭管理员确认过的内容，才会出现在你的记录里。
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
