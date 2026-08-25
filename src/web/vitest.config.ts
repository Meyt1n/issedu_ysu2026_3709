import { fileURLToPath, URL } from 'node:url'

import { defineConfig } from 'vitest/config'

export default defineConfig({
  test: {
    environment: 'node',
    include: ['src/web/src/**/*.test.ts', 'shared/voice/**/*.test.ts'],
    root: fileURLToPath(new URL('../..', import.meta.url)),
  },
  resolve: {
    alias: {
      '@': fileURLToPath(new URL('./src', import.meta.url)),
      '@hct/voice': fileURLToPath(new URL('../../shared/voice', import.meta.url)),
    },
  },
})
