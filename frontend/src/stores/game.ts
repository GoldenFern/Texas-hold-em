/** 游戏状态 store —— 唯一状态源,socket 事件在此落地。 */

import { defineStore } from 'pinia'
import { getSocket } from '@/api/socket'
import type {
  ActionName, GameUpdate, HandCompleted, NewGamePayload,
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
    /** 已发送动作等待服务器响应(F3:按钮禁用) */
    actionPending: false,
    handResult: null as HandCompleted | null,
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
        if (s.hand_id !== this.handId) {
          this.resetHandState()
          this.handId = s.hand_id
        }
        this.state = s
        this.gameStarted = true
        // 收到状态即认为上一动作已被处理
        this.actionPending = false
        const cp = s.players[s.current_player_index]
        if (this.thinking && cp && this.thinking.player !== cp.name) {
          this.thinking = null
        }
        if ((s.legal_actions?.length ?? 0) === 0) {
          this.actionRequired = false
        }
      })

      socket.on('action_required', (p) => {
        this.actionRequired = true
        this.actionTimeout = p.timeout_seconds
        this.thinking = null
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
        this.thinking = null
      })

      socket.on('game_over', (p) => {
        this.gameOverMessage = p.message
        this.gameStarted = false
        this.handResult = null
        this.actionRequired = false
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
      this.actionPending = false
      this.handResult = null
    },

    newGame(payload: NewGamePayload) {
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
      getSocket().emit('continue_game')
    },

    endGame() {
      getSocket().emit('end_game')
    },
  },
})
