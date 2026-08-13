import { existsSync } from 'node:fs'
import { defineConfig, devices } from '@playwright/test'

const localEdgePath = 'C:\\Program Files (x86)\\Microsoft\\Edge\\Application\\msedge.exe'
const browserPath = process.env.PLAYWRIGHT_BROWSER_PATH
  ?? (existsSync(localEdgePath) ? localEdgePath : undefined)

export default defineConfig({
  testDir: './tests/browser',
  forbidOnly: Boolean(process.env.CI),
  retries: process.env.CI ? 2 : 0,
  workers: 1,
  timeout: 60_000,
  expect: { timeout: 12_000 },
  reporter: process.env.CI
    ? [['list'], ['junit', { outputFile: 'artifacts/hct405-browser-junit.xml' }]]
    : 'list',
  use: {
    baseURL: 'http://127.0.0.1:5173',
    screenshot: 'only-on-failure',
    trace: 'retain-on-failure',
  },
  projects: [
    {
      name: 'chromium',
      use: {
        ...devices['Desktop Chrome'],
        ...(browserPath ? { launchOptions: { executablePath: browserPath } } : {}),
      },
    },
  ],
  webServer: {
    command: 'npm run dev:web -- --host 127.0.0.1',
    url: 'http://127.0.0.1:5173',
    reuseExistingServer: !process.env.CI,
    timeout: 120_000,
  },
})
