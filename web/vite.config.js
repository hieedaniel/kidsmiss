import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'

const TARGET = 'http://127.0.0.1:8770'

export default defineConfig({
  plugins: [vue()],
  base: '/',
  server: {
    port: 5173,
    proxy: {
      '/api': TARGET,
      '/uploads': TARGET,
      '/figs': TARGET,
    },
  },
  build: { outDir: 'dist', emptyOutDir: true },
})
