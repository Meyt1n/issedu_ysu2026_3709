import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'

export default defineConfig({
  root: 'src/web',
  plugins: [vue()],
  server: {
    port: 5173,
    proxy: {
      '/health': 'http://localhost:8000',
      '/api': 'http://localhost:8000',
    },
  },
})
