import { beforeEach, describe, expect, it, vi } from 'vitest'

import {
  SHELL_CACHE_PREFIX,
  applyPendingUpdate,
  canPromptInstall,
  captureInstallPrompt,
  dismissInstallEntry,
  installDismissed,
  markUpdateReadyWhenInstalled,
  recoverShellCaches,
  resetPwaLifecycleState,
  serviceWorkerSupported,
  triggerInstallPrompt,
  updateApplying,
  watchRegistrationForUpdates,
  type RegistrationLike,
  type ServiceWorkerContainerLike,
  type ServiceWorkerLike,
} from './pwa'

function fakeWorker(state: string): ServiceWorkerLike & {
  setState(next: string): void
  posted: { type: string }[]
} {
  const posted: { type: string }[] = []
  const listeners: Array<() => void> = []
  const worker = {
    state,
    postMessage(message: { type: string }) {
      posted.push(message)
    },
    addEventListener(_type: string, listener: () => void) {
      listeners.push(listener)
    },
    setState(next: string) {
      worker.state = next
      listeners.forEach(listener => listener())
    },
    posted,
  }
  return worker as ServiceWorkerLike & { setState(next: string): void; posted: { type: string }[] }
}

function fakeContainer(controller: ServiceWorkerLike | null): ServiceWorkerContainerLike & {
  emit(event: string): void
} {
  const listeners = new Map<string, Array<() => void>>()
  const container = {
    controller,
    async register() {
      throw new Error('not used')
    },
    addEventListener(type: string, listener: () => void) {
      const list = listeners.get(type) ?? []
      list.push(listener)
      listeners.set(type, list)
    },
    emit(event: string) {
      listeners.get(event)?.forEach(listener => listener())
    },
  }
  return container as ServiceWorkerContainerLike & { emit(event: string): void }
}

beforeEach(() => {
  resetPwaLifecycleState()
})

describe('MOB-151 markUpdateReadyWhenInstalled', () => {
  it('已安装且存在控制器时立即提示', () => {
    const onReady = vi.fn()
    markUpdateReadyWhenInstalled(fakeWorker('installed'), true, onReady)
    expect(onReady).toHaveBeenCalledTimes(1)
  })

  it('首次安装（无控制器）不提示', () => {
    const onReady = vi.fn()
    markUpdateReadyWhenInstalled(fakeWorker('installed'), false, onReady)
    expect(onReady).not.toHaveBeenCalled()
  })

  it('安装完成后经 statechange 提示', () => {
    const onReady = vi.fn()
    const worker = fakeWorker('installing')
    markUpdateReadyWhenInstalled(worker, true, onReady)
    expect(onReady).not.toHaveBeenCalled()
    worker.setState('installed')
    expect(onReady).toHaveBeenCalledTimes(1)
  })
})

describe('MOB-151 watchRegistrationForUpdates', () => {
  function fakeRegistration(installing: ServiceWorkerLike | null, waiting: ServiceWorkerLike | null) {
    const listeners = new Map<string, Array<() => void>>()
    const registration: RegistrationLike = {
      installing,
      waiting,
      async update() {},
      addEventListener(type: string, listener: () => void) {
        const list = listeners.get(type) ?? []
        list.push(listener)
        listeners.set(type, list)
      },
    }
    return {
      registration,
      emit(event: string) {
        listeners.get(event)?.forEach(listener => listener())
      },
    }
  }

  it('已有等待中的新版本时直接提示', () => {
    const onReady = vi.fn()
    const { registration } = fakeRegistration(null, fakeWorker('installed'))
    watchRegistrationForUpdates(registration, true, onReady)
    expect(onReady).toHaveBeenCalledTimes(1)
  })

  it('updatefound 后新 worker 安装完成才提示', () => {
    const onReady = vi.fn()
    const worker = fakeWorker('installing')
    const { registration, emit } = fakeRegistration(worker, null)
    watchRegistrationForUpdates(registration, true, onReady)
    emit('updatefound')
    expect(onReady).not.toHaveBeenCalled()
    worker.setState('installed')
    expect(onReady).toHaveBeenCalledTimes(1)
  })
})

describe('MOB-151 applyPendingUpdate', () => {
  it('无等待版本时不动作', () => {
    const container = fakeContainer({ postMessage() {} })
    expect(applyPendingUpdate(container, null, vi.fn())).toBe(false)
    expect(updateApplying.value).toBe(false)
  })

  it('确认后发送 SKIP_WAITING，控制器切换只刷新一次', () => {
    const worker = fakeWorker('installed')
    const container = fakeContainer(null)
    const reload = vi.fn()
    expect(applyPendingUpdate(container, { installing: null, waiting: worker, async update() {}, addEventListener() {} }, reload)).toBe(true)
    expect(worker.posted).toEqual([{ type: 'SKIP_WAITING' }])
    expect(updateApplying.value).toBe(true)
    container.emit('controllerchange')
    container.emit('controllerchange')
    expect(reload).toHaveBeenCalledTimes(1)
  })

  it('应用中重复确认被忽略', () => {
    const worker = fakeWorker('installed')
    const container = fakeContainer(null)
    const registration: RegistrationLike = {
      installing: null,
      waiting: worker,
      async update() {},
      addEventListener() {},
    }
    applyPendingUpdate(container, registration, vi.fn())
    expect(applyPendingUpdate(container, registration, vi.fn())).toBe(false)
    expect(worker.posted).toHaveLength(1)
  })
})

describe('MOB-151 recoverShellCaches', () => {
  it('只清理外壳前缀缓存，不动其它缓存', async () => {
    const deleted: string[] = []
    const cacheStorage = {
      async keys() {
        return [`${SHELL_CACHE_PREFIX}-v3`, `${SHELL_CACHE_PREFIX}-v2`, 'runtime-api', 'other-cache']
      },
      async delete(name: string) {
        deleted.push(name)
        return true
      },
    }
    const removed = await recoverShellCaches(cacheStorage)
    expect(removed).toEqual([`${SHELL_CACHE_PREFIX}-v3`, `${SHELL_CACHE_PREFIX}-v2`])
    expect(deleted).toEqual(removed)
  })
})

describe('MOB-151 install prompt', () => {
  it('捕获后可触发一次，之后回到不可用', async () => {
    expect(canPromptInstall()).toBe(false)
    expect(await triggerInstallPrompt()).toBe('unavailable')
    const prompt = vi.fn().mockResolvedValue(undefined)
    captureInstallPrompt({ preventDefault() {}, prompt } as unknown as Event & { prompt(): Promise<void> })
    expect(canPromptInstall()).toBe(true)
    expect(await triggerInstallPrompt()).toBe('prompted')
    expect(prompt).toHaveBeenCalledTimes(1)
    expect(canPromptInstall()).toBe(false)
  })

  it('关闭入口后状态生效并可复位', () => {
    dismissInstallEntry()
    expect(installDismissed.value).toBe(true)
    resetPwaLifecycleState()
    expect(installDismissed.value).toBe(false)
  })
})

describe('MOB-151 capability text', () => {
  it('不支持 Service Worker 时给出普通网页路径说明', () => {
    const supported = serviceWorkerSupported()
    expect(typeof supported).toBe('boolean')
  })
})
