/** 回放 store —— 逐步渲染 step_snapshots。 */

import { defineStore } from 'pinia'
import type { ReplayData, ReplaySummary } from '@/api/protocol'
import { fetchReplay, fetchReplayList } from '@/api/rest'

export const useReplayStore = defineStore('replay', {
  state: () => ({
    list: [] as ReplaySummary[],
    current: null as ReplayData | null,
    stepIndex: 0,
    active: false,
  }),

  getters: {
    snapshot: (s) => s.current?.step_snapshots[s.stepIndex] ?? null,
    maxStep: (s) => Math.max(0, (s.current?.step_snapshots.length ?? 1) - 1),
    /** 当前步对应的动作(快照 0 为盲注前,动作 i 产生快照 i+1)。 */
    currentAction: (s) => {
      if (!s.current || s.stepIndex === 0) return null
      return s.current.actions[s.stepIndex - 1] ?? null
    },
  },

  actions: {
    async loadList() {
      this.list = await fetchReplayList()
    },
    async open(handId?: number) {
      this.current = await fetchReplay(handId)
      this.stepIndex = 0
      this.active = true
    },
    close() {
      this.active = false
      this.current = null
      this.stepIndex = 0
    },
    next() {
      if (this.stepIndex < this.maxStep) this.stepIndex += 1
    },
    prev() {
      if (this.stepIndex > 0) this.stepIndex -= 1
    },
  },
})
