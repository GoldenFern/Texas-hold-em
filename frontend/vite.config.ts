import { fileURLToPath, URL } from 'node:url'
import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'

// 开发: Vite :5173 代理到 Flask :5000;生产: 构建产物输出到 ../static/dist 由 Flask 直接服务
// base 只在 build 时指向 /static/dist/,dev 用 / ——否则源码模块会被 /static 代理转发成 404
export default defineConfig(({ command }) => ({
  plugins: [vue()],
  resolve: {
    alias: { '@': fileURLToPath(new URL('./src', import.meta.url)) },
  },
  server: {
    proxy: {
      '/api': { target: 'http://127.0.0.1:5000', changeOrigin: true },
      '/static': { target: 'http://127.0.0.1:5000', changeOrigin: true },
      '/socket.io': { target: 'http://127.0.0.1:5000', changeOrigin: true, ws: true },
    },
  },
  build: {
    outDir: '../static/dist',
    emptyOutDir: true,
  },
  base: command === 'build' ? '/static/dist/' : '/',
}))
