/** 非阻塞 Toast 通知 store（替代旧 alert(),F6）。 */

import { defineStore } from 'pinia'

export interface Toast {
  id: number
  kind: 'info' | 'warn' | 'error'
  text: string
}

let nextId = 1

export const useToastStore = defineStore('toast', {
  state: () => ({ toasts: [] as Toast[] }),
  actions: {
    push(kind: Toast['kind'], text: string, ttlMs = 4000) {
      const id = nextId++
      this.toasts.push({ id, kind, text })
      setTimeout(() => this.dismiss(id), ttlMs)
    },
    info(text: string) { this.push('info', text) },
    warn(text: string) { this.push('warn', text) },
    error(text: string) { this.push('error', text, 8000) },
    dismiss(id: number) {
      this.toasts = this.toasts.filter((t) => t.id !== id)
    },
  },
})
