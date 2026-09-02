import { createApp, defineComponent, nextTick } from 'vue'
import { createMemoryHistory, createRouter } from 'vue-router'
import { afterEach, describe, expect, it } from 'vitest'

import AssistantEvidencePanel from './AssistantEvidencePanel.vue'

const citation = {
  document_id: 'demo-doc-medication-basics',
  version: 'idx-demo-2026-08',
  chunk_id: 'chunk-2',
  document_title: '家庭用药安全（演示）',
  text: '演示片段：服药前请核对药品名称和有效期。',
  locator: '第 2 段',
}

const mountedApps: Array<{ unmount: () => void }> = []
const EmptyView = defineComponent({ template: '<div />' })

async function mountPanel(props: Record<string, unknown>) {
  const router = createRouter({
    history: createMemoryHistory(),
    routes: [
      { name: 'home', path: '/', component: EmptyView },
      { name: 'knowledge-document', path: '/knowledge/:docId', component: EmptyView },
    ],
  })
  router.push('/')
  await router.isReady()

  const host = document.createElement('div')
  document.body.appendChild(host)
  const app = createApp(AssistantEvidencePanel, props)
  app.use(router)
  app.mount(host)
  mountedApps.push(app)
  await nextTick()
  return { host, router }
}

afterEach(() => {
  for (const app of mountedApps.splice(0)) app.unmount()
  document.body.replaceChildren()
})

describe('AssistantEvidencePanel', () => {
  it('默认折叠依据，并按来源、原文、版本展示引用详情', async () => {
    const { host } = await mountPanel({ citations: [citation, citation] })

    const details = host.querySelector('details')
    expect(details).not.toBeNull()
    expect(details?.open).toBe(false)
    expect(host.querySelector('.assistant-evidence-summary')?.textContent).toContain('1 条引用')
    expect(host.querySelector('.assistant-citation-heading')?.textContent).toContain('家庭用药安全（演示）')
    expect(host.querySelector('.assistant-citation-text')?.textContent).toContain('核对药品名称')
    expect(host.querySelector('.assistant-citation-card .meta-line')?.textContent).toContain('idx-demo-2026-08')

    const link = host.querySelector<HTMLAnchorElement>('.assistant-citation-detail')
    expect(link?.getAttribute('href')).toContain('/knowledge/demo-doc-medication-basics')
    expect(link?.getAttribute('href')).toContain('chunk=chunk-2')
    expect(link?.getAttribute('href')).toContain('version=idx-demo-2026-08')
  })

  it('降级回答显示明确无依据提示，而不是空白依据区', async () => {
    const { host } = await mountPanel({ degraded: true, degradeReason: '家庭服务器暂不可达' })

    expect(host.querySelector('details')).not.toBeNull()
    expect(host.querySelector('.assistant-no-evidence')?.textContent).toContain('没有可引用的知识文档')
    expect(host.querySelector('.assistant-no-evidence')?.textContent).toContain('家庭服务器暂不可达')
    expect(host.querySelector('.assistant-citation-card')).toBeNull()
  })
})
