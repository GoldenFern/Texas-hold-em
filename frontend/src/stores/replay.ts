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
    playing: false,
    speed: 1,
    timer: null as number | null,
  }),

  getters: {
    snapshot: (s) => s.current?.step_snapshots[s.stepIndex] ?? null,
    maxStep: (s) => Math.max(0, (s.current?.step_snapshots.length ?? 1) - 1),
    /** 当前步对应的动作(快照 0 为盲注前,动作 i 产生快照 i+1)。 */
    currentAction: (s) => {
      if (!s.current || s.stepIndex === 0) return null
      return s.current.actions[s.stepIndex - 1] ?? null
    },
    phaseStops: (s) => {
      if (!s.current) return [] as { phase: string; step: number }[]
      const stops: { phase: string; step: number }[] = []
      let previous = ''
      s.current.step_snapshots.forEach((snapshot, step) => {
        if (snapshot.phase !== previous) {
          previous = snapshot.phase
          if (snapshot.phase !== 'WAITING') stops.push({ phase: snapshot.phase, step })
        }
      })
      return stops
    },
  },

  actions: {
    async loadList() {
      this.list = await fetchReplayList()
    },
    async open(handId?: number) {
      this.pause()
      this.current = await fetchReplay(handId)
      this.stepIndex = 0
      this.active = true
    },
    close() {
      this.pause()
      this.active = false
      this.current = null
      this.stepIndex = 0
    },
    next() {
      if (this.stepIndex < this.maxStep) this.stepIndex += 1
      if (this.stepIndex >= this.maxStep) this.pause()
    },
    prev() {
      this.pause()
      if (this.stepIndex > 0) this.stepIndex -= 1
    },
    play() {
      if (!this.active || this.playing || this.stepIndex >= this.maxStep) return
      this.playing = true
      this.timer = window.setInterval(() => this.next(), Math.round(850 / this.speed))
    },
    pause() {
      if (this.timer !== null) window.clearInterval(this.timer)
      this.timer = null
      this.playing = false
    },
    togglePlay() {
      if (this.playing) this.pause()
      else this.play()
    },
    setSpeed(speed: number) {
      this.speed = Math.max(.5, Math.min(2, speed))
      if (this.playing) {
        this.pause()
        this.play()
      }
    },
    jumpTo(step: number) {
      this.stepIndex = Math.max(0, Math.min(this.maxStep, Math.round(step)))
    },
  },
})
