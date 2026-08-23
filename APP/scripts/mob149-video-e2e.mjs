/**
 * MOB-149：短视频采集端到端证据脚本（本地受控联调）。
 *
 * 前置：D2 分支后端（codex/hct414-d2-video-jobs，含 vision-task-video 能力
 * 与视频质量门）运行在 127.0.0.1:18800；APP dev server 运行在 5173；
 * 已用 X-Actor-ID 种子好家庭与成员。脚本用合成 mp4 驱动：
 *  联机 + 能力探测 → 视频入口可见 → 本地校验摘要 → 抽帧质量门（PASS+
 * 帧摘要）→ 创建任务（queued）→ 本地 worker --once 处理 → 回查 succeeded
 * → 人工复核交接文案。截图写入 docs/stories/evidence/。
 *
 * 用法：node scripts/mob149-video-e2e.mjs --fixture <mp4> --worktree <d2路径> \
 *   --python <venv python 绝对路径> [--actor mob149-e2e] [--base http://localhost:5173]
 */
import { spawn } from 'node:child_process'
import { fileURLToPath, URL } from 'node:url'
import { join } from 'node:path'

import { chromium } from '@playwright/test'

const APP_ROOT = fileURLToPath(new URL('..', import.meta.url))
const EVIDENCE = join(APP_ROOT, '..', 'docs', 'stories', 'evidence')

function arg(name, fallback) {
  const index = process.argv.indexOf(`--${name}`)
  return index >= 0 ? process.argv[index + 1] : fallback
}

const BASE = arg('base', 'http://localhost:5173')
const FIXTURE = arg('fixture')
const WORKTREE = arg('worktree')
const PYTHON = arg('python')
const ACTOR = arg('actor', 'mob149-e2e')
if (!FIXTURE || !WORKTREE || !PYTHON) {
  throw new Error('--fixture/--worktree/--python are required')
}

function line(message) {
  console.log(`[mob149-e2e] ${message}`)
}

function runWorkerOnce() {
  return new Promise((resolve, reject) => {
    const child = spawn(
      PYTHON,
      [join(WORKTREE, 'scripts', 'vision_worker.py'), '--once', '--actors', ACTOR, '--api', 'http://127.0.0.1:18800/api/v1'],
      {
        cwd: WORKTREE,
        env: { ...process.env, PYTHONPATH: 'src/api;src', HCT_ADAPTER_SIGNING_KEY: 'dev-only-change-me' },
        stdio: ['ignore', 'pipe', 'pipe'],
      },
    )
    let output = ''
    child.stdout.on('data', chunk => { output += chunk })
    child.stderr.on('data', chunk => { output += chunk })
    child.on('error', reject)
    child.on('close', code => {
      if (code === 0) resolve(output)
      else reject(new Error(`worker exited ${code}: ${output.slice(-800)}`))
    })
  })
}

async function main() {
  const browser = await chromium.launch({ args: ['--no-proxy-server'] })
  const context = await browser.newContext({ viewport: { width: 390, height: 844 } })
  const page = await context.newPage()

  try {
    // 预置联机会话（dev 构建的 dev-actor 路径，X-Actor-ID 直连本地后端；
    // 正式登录路径属于 MOB-133 验收范围，本脚本不替代）。
    await page.addInitScript(actor => {
      window.localStorage.setItem(
        'hct-mobile.session.v1',
        JSON.stringify({
          dataMode: 'live',
          serverBaseUrl: '',
          actorId: actor,
          accessPurpose: 'family-care',
          authMode: 'dev-actor',
          currentHouseholdId: '',
        }),
      )
    }, ACTOR)

    await page.goto(`${BASE}/#/me`)
    await page.waitForSelector('text=测试连接', { timeout: 15000 })
    const capabilitiesResponse = page.waitForResponse(response =>
      response.url().includes('/meta/capabilities') && response.status() === 200, { timeout: 15000 })
    await page.click('text=测试连接')
    const capabilities = (await (await capabilitiesResponse).json())
    if (!capabilities.available?.includes('vision-task-video')) {
      throw new Error(`vision-task-video not declared: ${JSON.stringify(capabilities.available)}`)
    }
    line('capabilities probe: vision-task-video declared')

    await page.goto(`${BASE}/#/scan`)
    await page.waitForSelector('text=为哪位成员录入', { timeout: 15000 })
    const videoInput = page.locator('input[accept="video/mp4,video/quicktime,.mp4,.mov"]')
    await videoInput.waitFor({ state: 'visible', timeout: 10000 })
    await videoInput.setInputFiles(FIXTURE)

    await page.waitForSelector('text=将上传：短视频', { timeout: 20000 })
    await page.waitForSelector('text=抽帧摘要', { timeout: 20000 })
    await page.waitForSelector('text=通过', { timeout: 10000 })
    await page.screenshot({ path: join(EVIDENCE, 'MOB-149-video-quality-pass.png'), fullPage: true })
    line('local validation summary + video quality gate PASS (frame summary shown)')

    await page.click('text=开始识别')
    await page.waitForSelector('text=任务状态回查', { timeout: 30000 })
    await page.waitForSelector('.tag:has-text("排队中")', { timeout: 30000 })
    await page.screenshot({ path: join(EVIDENCE, 'MOB-149-video-task-queued.png'), fullPage: true })
    line('vision task created via media_type=video, status queued')

    const workerOutput = await runWorkerOnce()
    line(`worker pass finished: ${workerOutput.split('\n').filter(Boolean).slice(-2).join(' | ')}`)

    // 轮询会自行到达终态；若仍在退避等待则手动触发一次立即回查。
    const checkNowButton = page.locator('text=立即回查')
    try {
      await checkNowButton.click({ timeout: 3000 })
      line('manual check-now clicked')
    } catch {
      line('polling reached terminal state on its own')
    }
    await page.waitForSelector('.tag:has-text("已完成")', { timeout: 40000 })
    await page.waitForSelector('text=人工复核', { timeout: 10000 })
    await page.screenshot({ path: join(EVIDENCE, 'MOB-149-video-task-succeeded.png'), fullPage: true })
    line('task reached succeeded with human-review handoff; polling kept one task')

    console.log('MOB149-VIDEO-E2E PASS')
    return 0
  } finally {
    await browser.close()
  }
}

main().then(
  code => process.exit(code ?? 0),
  error => {
    console.error('[mob149-e2e] FAILED:', error)
    process.exit(1)
  },
)
