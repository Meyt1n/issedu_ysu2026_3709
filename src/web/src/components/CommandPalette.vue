<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'

import {
  pushToast,
  selectMember,
  session,
  setView,
  signOut,
  type ViewName,
} from '../store'
import { filterCommands, flattenCommands, type CommandGroup } from '../ui/commands'
import { THEMES, applyTheme } from '../ui/themes'
import AppIcon from './AppIcon.vue'

const props = defineProps<{
  navItems: Array<{ view: ViewName; label: string; icon: string; group: string }>
}>()

const open = ref(false)
const query = ref('')
const activeIndex = ref(0)
const inputEl = ref<HTMLInputElement | null>(null)
const listEl = ref<HTMLElement | null>(null)

function close(): void {
  open.value = false
}

function show(): void {
  query.value = ''
  activeIndex.value = 0
  open.value = true
  void nextTick(() => inputEl.value?.focus())
}

function toggle(): void {
  if (open.value) close()
  else show()
}

defineExpose({ toggle, show })

const groups = computed<CommandGroup[]>(() => {
  const nav: CommandGroup = {
    name: '页面',
    items: props.navItems.map(item => ({
      id: `nav:${item.view}`,
      label: item.label,
      hint: item.group,
      keywords: item.view,
      icon: item.icon,
      run: () => setView(item.view),
    })),
  }

  const members: CommandGroup = {
    name: '成员档案',
    items: session.members.map(member => ({
      id: `member:${member.id}`,
      label: `查看成员：${member.display_name}`,
      hint: '打开成员档案',
      keywords: `member ${member.display_name}`,
      icon: 'members',
      run: () => {
        selectMember(member.id)
        setView('members')
      },
    })),
  }

  const themes: CommandGroup = {
    name: '界面主题',
    items: THEMES.map(theme => ({
      id: `theme:${theme.id}`,
      label: `主题：${theme.name}`,
      hint: theme.tagline,
      keywords: `theme ${theme.id}`,
      icon: 'palette',
      run: () => {
        applyTheme(theme.id)
        pushToast('success', `已切换到「${theme.name}」主题。`)
      },
    })),
  }

  const actions: CommandGroup = {
    name: '动作',
    items: [
      {
        id: 'action:record',
        label: '记一笔健康事实',
        hint: '到成员档案手工录入',
        keywords: 'record entry 记录',
        icon: 'plus',
        run: () => setView('members'),
      },
      {
        id: 'action:signout',
        label: '退出当前身份',
        hint: '回到进入页',
        keywords: 'sign out logout 退出',
        icon: 'signout',
        run: () => signOut(),
      },
    ],
  }

  return [nav, members, themes, actions]
})

const filtered = computed(() => filterCommands(groups.value, query.value))
const flat = computed(() => flattenCommands(filtered.value))

watch([query, filtered], () => {
  if (activeIndex.value >= flat.value.length) activeIndex.value = 0
})

// 键盘上下移动时让高亮项保持在可视区域内
watch(activeIndex, () => {
  void nextTick(() => {
    listEl.value
      ?.querySelector('.palette-item.active')
      ?.scrollIntoView({ block: 'nearest' })
  })
})

function runItem(index: number): void {
  const item = flat.value[index]
  if (!item) return
  close()
  item.run()
}

function move(delta: number): void {
  const count = flat.value.length
  if (count === 0) return
  activeIndex.value = (activeIndex.value + delta + count) % count
}

function indexOfItem(id: string): number {
  return flat.value.findIndex(item => item.id === id)
}

function onGlobalKeydown(event: KeyboardEvent): void {
  if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === 'k') {
    event.preventDefault()
    toggle()
    return
  }
  if (!open.value) return
  if (event.key === 'Escape') {
    event.preventDefault()
    close()
  } else if (event.key === 'ArrowDown') {
    event.preventDefault()
    move(1)
  } else if (event.key === 'ArrowUp') {
    event.preventDefault()
    move(-1)
  } else if (event.key === 'Enter') {
    event.preventDefault()
    runItem(activeIndex.value)
  }
}

onMounted(() => window.addEventListener('keydown', onGlobalKeydown))
onBeforeUnmount(() => window.removeEventListener('keydown', onGlobalKeydown))
</script>

<template>
  <Teleport to="body">
    <Transition name="modal">
      <div
        v-if="open"
        class="palette-backdrop"
        role="dialog"
        aria-modal="true"
        aria-label="命令面板"
        @click.self="close"
      >
        <div class="palette-card">
          <div class="palette-input-row">
            <AppIcon name="compass" :size="17" />
            <input
              ref="inputEl"
              v-model="query"
              class="palette-input"
              type="text"
              placeholder="搜索页面、成员、主题或动作…"
              aria-label="搜索命令"
              autocomplete="off"
              spellcheck="false"
            />
            <kbd class="palette-kbd">Esc</kbd>
          </div>

          <div ref="listEl" class="palette-list" role="listbox" aria-label="命令列表">
            <template v-for="group in filtered" :key="group.name">
              <p class="palette-group-label">{{ group.name }}</p>
              <button
                v-for="item in group.items"
                :key="item.id"
                type="button"
                class="palette-item"
                role="option"
                :aria-selected="indexOfItem(item.id) === activeIndex"
                :class="{ active: indexOfItem(item.id) === activeIndex }"
                @pointerenter="activeIndex = indexOfItem(item.id)"
                @click="runItem(indexOfItem(item.id))"
              >
                <AppIcon :name="item.icon" :size="16" />
                <span class="palette-item-label">{{ item.label }}</span>
                <span class="palette-item-hint">{{ item.hint }}</span>
              </button>
            </template>
            <div v-if="flat.length === 0" class="palette-empty">
              没有匹配「{{ query }}」的命令；这里不提供购药、问诊或广告入口。
            </div>
          </div>

          <div class="palette-foot">
            <span><kbd class="palette-kbd">↑</kbd><kbd class="palette-kbd">↓</kbd> 选择</span>
            <span><kbd class="palette-kbd">Enter</kbd> 执行</span>
            <span><kbd class="palette-kbd">Ctrl</kbd><kbd class="palette-kbd">K</kbd> 开关</span>
          </div>
        </div>
      </div>
    </Transition>
  </Teleport>
</template>
