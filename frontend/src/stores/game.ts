/** 游戏状态 store —— 唯一状态源,socket 事件在此落地。 */

import { defineStore } from 'pinia'
import { getSocket } from '@/api/socket'
import type {
  ActionApplied, ActionName, GameUpdate, HandCompleted, NewGamePayload,
} from '@/api/protocol'
import { zh } from '@/i18n/zh'
import { useToastStore } from './toast'

export interface ThinkingState {
  player: string
  isLlm: boolean
}

export const useGameStore = defineStore('game', {
  state: () => ({
    connected: false,
    state: null as GameUpdate | null,
    /** 当前手牌 id,变化时触发 resetHandState(F1:防状态残留) */
    handId: 0,
    thinking: null as ThinkingState | null,
    actionRequired: false,
    actionTimeout: 60,
    actionDeadlineAt: null as number | null,
    /** 已发送动作等待服务器响应(F3:按钮禁用) */
    actionPending: false,
    /** 当前手牌的最近动作,按 hand_id/action_index 去重。 */
    actionFeed: [] as ActionApplied[],
    handResult: null as HandCompleted | null,
    reviewHandId: null as number | null,
    reviewingHand: false,
    gameOverMessage: '' as string,
    gameStarted: false,
  }),

  getters: {
    humanPlayer: (s) => s.state?.players.find((p) => p.is_human) ?? null,
    isHumanTurn(): boolean {
      if (!this.state || !this.humanPlayer) return false
      const cp = this.state.players[this.state.current_player_index]
      return cp?.name === this.humanPlayer.name
        && (this.state.legal_actions?.length ?? 0) > 0
        && this.state.phase !== 'FINISHED'
    },
    analysis: (s) => s.state?.analysis ?? null,
  },

  actions: {
    /** 绑定 socket 事件(App 挂载时调用一次)。 */
    bind() {
      const socket = getSocket()
      const toast = useToastStore()

      socket.on('connect', () => { this.connected = true })
      socket.on('disconnect', () => {
        this.connected = false
        toast.warn(zh.errors.disconnected)
      })

      socket.on('game_update', (s) => {
        // 异步分析可能晚于新动作到达,旧 action_index 不得覆盖新状态。
        if (
          s.hand_id === this.handId
          && this.state
          && s.action_index < this.state.action_index
        ) return
        if (s.hand_id !== this.handId) {
          this.resetHandState()
          this.handId = s.hand_id
        }
        // 同一动作的重连/基础广播可能没有 analysis,保留已经完成的 MC 结果。
        this.state = (
          this.state
          && s.hand_id === this.state.hand_id
          && s.action_index === this.state.action_index
          && !s.analysis
          && this.state.analysis
        )
          ? { ...s, analysis: this.state.analysis }
          : s
        this.gameStarted = true
        // 收到状态即认为上一动作已被处理
        this.actionPending = false
        const cp = s.players[s.current_player_index]
        if (this.thinking && cp && this.thinking.player !== cp.name) {
          this.thinking = null
        }
        if ((s.legal_actions?.length ?? 0) === 0) {
          this.actionRequired = false
          this.actionDeadlineAt = null
        }
      })

      socket.on('action_required', (p) => {
        // 首次重连可能先收到倒计时再收到 game_update,先接住同手牌事件。
        if (this.handId !== 0 && p.hand_id !== this.handId) return
        if (this.handId === 0) this.handId = p.hand_id
        this.actionRequired = true
        this.actionTimeout = p.timeout_seconds
        this.actionDeadlineAt = p.deadline_at
        this.thinking = null
      })

      socket.on('action_applied', (p) => {
        if (this.handId !== 0 && p.hand_id !== this.handId) return
        if (this.handId === 0) this.handId = p.hand_id
        const duplicate = this.actionFeed.some(
          (item) => item.hand_id === p.hand_id && item.action_index === p.action_index,
        )
        if (duplicate) return
        this.actionFeed.push(p)
        if (this.actionFeed.length > 24) this.actionFeed.shift()
        if (this.state?.hand_id === p.hand_id && p.action_index + 1 > this.state.action_index) {
          this.state.action_index = p.action_index + 1
        }
        this.actionPending = false
        this.actionRequired = false
        this.actionDeadlineAt = null
      })

      socket.on('bot_thinking', (p) => {
        this.thinking = { player: p.player, isLlm: p.is_llm }
      })

      socket.on('action_rejected', (p) => {
        this.actionPending = false
        toast.warn(`${p.reason}`)
      })

      socket.on('llm_status', (p) => {
        if (p.status === 'ok') return
        const kindText = p.error_type ? zh.llmStatus[p.error_type] ?? p.error_type : ''
        const base = zh.llmStatus[p.status] ?? p.status
        toast.info(`${p.player}: ${base}${kindText ? `（${kindText}）` : ''}`)
      })

      socket.on('hand_completed', (p) => {
        this.handResult = p
        this.actionRequired = false
        this.actionDeadlineAt = null
        this.thinking = null
      })

      socket.on('game_over', (p) => {
        this.gameOverMessage = p.message
        this.gameStarted = false
        this.handResult = null
        this.actionRequired = false
        this.actionDeadlineAt = null
        this.thinking = null
      })

      socket.on('game_error', (p) => {
        toast.error(p.message)
      })
    },

    /** 新一手开始:清空上一手的瞬时状态(F1)。 */
    resetHandState() {
      this.thinking = null
      this.actionRequired = false
      this.actionDeadlineAt = null
      this.actionPending = false
      this.handResult = null
      this.actionFeed = []
      this.reviewHandId = null
      this.reviewingHand = false
    },

    newGame(payload: NewGamePayload) {
      this.resetHandState()
      this.state = null
      this.handId = 0
      this.gameStarted = false
      this.gameOverMessage = ''
      this.handResult = null
      getSocket().emit('new_game', payload)
    },

    sendAction(action: ActionName, amount = 0) {
      if (this.actionPending) return
      this.actionPending = true
      getSocket().emit('player_action', { action, amount })
    },

    continueGame() {
      this.handResult = null
      this.reviewHandId = null
      this.reviewingHand = false
      getSocket().emit('continue_game')
    },

    endGame() {
      this.reviewHandId = null
      this.reviewingHand = false
      getSocket().emit('end_game')
    },

    openReview(handId: number) {
      this.reviewHandId = handId
      this.reviewingHand = true
    },

    clearReviewRequest() {
      this.reviewHandId = null
    },

    exitReview() {
      this.reviewHandId = null
      this.reviewingHand = false
    },
  },
})
