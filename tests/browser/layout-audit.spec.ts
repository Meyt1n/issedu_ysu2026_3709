import { expect, test, type Page } from '@playwright/test'

import { submitFormalLogin } from './support/formalLogin'
import { installAuditApi } from './support/layoutAuditApi'

/**
 * 排版审计：在饱满的合成数据下量化检测「真实可见的」溢出与卡片错位。
 * 诊断脚本 —— 只打印发现，不做断言。
 */

const VIEWS = [
  { view: 'overview', label: '家庭总览' },
  { view: 'members', label: '成员档案' },
  { view: 'plans', label: '健康计划' },
  { view: 'scan', label: '视觉扫描' },
  { view: 'review', label: '人工复核' },
  { view: 'risks', label: '用药安全' },
  { view: 'graph', label: '健康图谱' },
  { view: 'bigscreen', label: '家庭大屏' },
] as const

const SIZES = [
  { width: 1440, height: 900, name: '1440' },
  { width: 1280, height: 800, name: '1280' },
  { width: 1024, height: 768, name: '1024' },
] as const

async function signIn(page: Page, width: number, height: number): Promise<void> {
  await page.setViewportSize({ width, height })
  await installAuditApi(page)
  await page.goto('/?portal=admin')
  await submitFormalLogin(page, 'audit-admin')
  await expect(page.locator('.app-frame')).toBeVisible({ timeout: 15_000 })
}

async function gotoView(page: Page, label: string): Promise<void> {
  // 「人工复核」按钮里含待复核角标，可及名会带上「9+」，所以按 .nav-label 定位。
  await page
    .locator('aside.sidebar .nav-item')
    .filter({ has: page.locator('.nav-label', { hasText: new RegExp(`^${label}$`) }) })
    .click()
  await page.waitForTimeout(1200)
}

async function auditPage(page: Page, tag: string): Promise<string[]> {
  return page.evaluate(label => {
    const problems: string[] = []
    const seen = new Set<string>()
    const add = (line: string): void => {
      if (seen.has(line)) return
      seen.add(line)
      problems.push(line)
    }
    const describe = (el: Element): string => {
      const cls = (el.className || '').toString().split(/\s+/).filter(Boolean).join('.')
      return `${el.tagName.toLowerCase()}${cls ? `.${cls}` : ''}`.slice(0, 90)
    }
    const clips = (el: Element): boolean => {
      const style = getComputedStyle(el)
      return style.overflow !== 'visible' || style.clipPath !== 'none'
    }
    /* 跑马灯是刻意超宽再动画平移的，父级 overflow 已裁剪，不算缺陷。 */
    const byDesign = (el: Element): boolean => !!el.closest('.bs-ticker')

    /* ── 1. 真实可见溢出：元素画到了最近的裁剪祖先之外 ── */
    document.querySelectorAll<HTMLElement>('.view-container *').forEach(el => {
      if (byDesign(el)) return
      const box = el.getBoundingClientRect()
      if (box.width === 0 || box.height === 0) return
      let ancestor = el.parentElement
      while (ancestor && !clips(ancestor)) ancestor = ancestor.parentElement
      if (!ancestor) return
      const ab = ancestor.getBoundingClientRect()
      const right = box.right - ab.right
      const left = ab.left - box.left
      if (right > 1.5) add(`可见右溢出 ${describe(el)} 超出 ${describe(ancestor)} +${right.toFixed(1)}px`)
      if (left > 1.5) add(`可见左溢出 ${describe(el)} 超出 ${describe(ancestor)} +${left.toFixed(1)}px`)
    })

    /* ── 2. 文本被裁：overflow hidden 且横向内容更宽（真的看不全） ── */
    document.querySelectorAll<HTMLElement>('.view-container *').forEach(el => {
      if (el.children.length > 0 || byDesign(el)) return
      const text = el.textContent?.trim() ?? ''
      if (!text) return
      const style = getComputedStyle(el)
      if (style.overflowX === 'visible' || style.position === 'absolute') return
      if (el.scrollWidth > el.clientWidth + 2 && el.clientWidth > 0) {
        const hidden = el.scrollWidth - el.clientWidth
        add(
          `文本被横向裁切 ${describe(el)}: 少 ${hidden}px（${el.scrollWidth}>${el.clientWidth}）「${text.slice(0, 22)}」`,
        )
      }
    })

    /* ── 3. 同一 grid 行的兄弟卡片：顶边应齐、底边应齐 ──
       显式 align-items:start 的容器（主+侧栏）本就按内容取高，不要求底边齐。 */
    document
      .querySelectorAll<HTMLElement>(
        '.home-dashboard-grid, .bs-columns, .grid-main-side, .bigscreen-grid, .section-stack',
      )
      .forEach(grid => {
        const gridAlign = getComputedStyle(grid).alignItems
        const expectEqualHeight = gridAlign !== 'start' && gridAlign !== 'flex-start' && gridAlign !== 'baseline'
        const kids = Array.from(grid.children).filter(
          (el): el is HTMLElement =>
            el instanceof HTMLElement &&
            el.getBoundingClientRect().height > 0 &&
            getComputedStyle(el).position !== 'sticky',
        )
        const rows = new Map<number, HTMLElement[]>()
        kids.forEach(kid => {
          const top = Math.round(kid.getBoundingClientRect().top)
          const bucket = [...rows.keys()].find(key => Math.abs(key - top) < 4)
          if (bucket === undefined) rows.set(top, [kid])
          else rows.get(bucket)!.push(kid)
        })
        rows.forEach(row => {
          if (row.length < 2) return
          const boxes = row.map(el => el.getBoundingClientRect())
          const topSpread = Math.max(...boxes.map(b => b.top)) - Math.min(...boxes.map(b => b.top))
          const bottomSpread =
            Math.max(...boxes.map(b => b.bottom)) - Math.min(...boxes.map(b => b.bottom))
          if (topSpread > 2) add(`同行顶边错位 ${describe(grid)}: ${topSpread.toFixed(1)}px`)
          if (expectEqualHeight && bottomSpread > 2) {
            add(
              `同行底边不齐 ${describe(grid)}: ${bottomSpread.toFixed(1)}px [${row.map(describe).join(' | ')}]`,
            )
          }
        })
      })

    /* ── 4. 顶层区块左右边缘应对齐同一阅读列 ── */
    const topLevel = Array.from(document.querySelectorAll<HTMLElement>('.view-container > *')).filter(
      el => el.getBoundingClientRect().height > 4 && getComputedStyle(el).position !== 'fixed',
    )
    if (topLevel.length > 1) {
      const lefts = topLevel.map(el => Math.round(el.getBoundingClientRect().left))
      const rights = topLevel.map(el => Math.round(el.getBoundingClientRect().right))
      const leftSpread = Math.max(...lefts) - Math.min(...lefts)
      const rightSpread = Math.max(...rights) - Math.min(...rights)
      if (leftSpread > 2) {
        const maxLeft = Math.max(...lefts)
        add(
          `顶层左边缘不齐 ${leftSpread}px [${topLevel.filter(el => Math.round(el.getBoundingClientRect().left) === maxLeft).map(describe).join(' | ')}]`,
        )
      }
      if (rightSpread > 2) {
        const maxRight = Math.max(...rights)
        add(
          `顶层右边缘不齐 ${rightSpread}px [${topLevel.filter(el => Math.round(el.getBoundingClientRect().right) !== maxRight).map(describe).join(' | ')}]`,
        )
      }
    }

    /* ── 5. 卡片内部大片空白：卡片底边距最后一块内容过远 ──
       注意用 Element 而非 HTMLElement：SVG 是 SVGElement，
       用 HTMLElement 判定会漏掉纯图表卡片的主体，误报一片空白。 */
    document
      .querySelectorAll<HTMLElement>('.home-dashboard-card, .bs-panel, .card')
      .forEach(card => {
        const kids = Array.from(card.children).filter(el => el.getBoundingClientRect().height > 0)
        if (kids.length === 0) return
        const contentBottom = Math.max(...kids.map(k => k.getBoundingClientRect().bottom))
        const slack = card.getBoundingClientRect().bottom - contentBottom
        const padBottom = Number.parseFloat(getComputedStyle(card).paddingBottom) || 0
        if (slack - padBottom > 60) {
          add(`卡片内部空白 ${describe(card)}: ${Math.round(slack - padBottom)}px`)
        }
      })

    return problems.map(line => `[${label}] ${line}`)
  }, tag)
}

for (const size of SIZES) {
  test(`layout audit @${size.name}`, async ({ page }) => {
    test.setTimeout(180_000)
    const findings: string[] = []
    await signIn(page, size.width, size.height)

    for (const target of VIEWS) {
      await gotoView(page, target.label)
      findings.push(...(await auditPage(page, `${size.name}/${target.view}`)))
    }

    console.log(`\n===== ${size.name} =====`)
    if (findings.length === 0) console.log('(无发现)')
    else findings.forEach(line => console.log(line))
    expect(true).toBe(true)
  })
}
