/** 设置 store —— 对局参数、Provider 预设、牌组皮肤(localStorage)。 */

import { defineStore } from 'pinia'
import type { BotConfig, BettingStructure, LlmConfigPayload } from '@/api/protocol'
import { fetchBotStyles, fetchLlmConfig, saveLlmConfig } from '@/api/rest'
import type { BotStyleInfo } from '@/api/protocol'
import {
  DECK_SKINS, loadPreferredSkin, savePreferredSkin, type DeckSkin,
} from '@/utils/deckSkin'
import {
  HAPTICS_KEY, SOUND_KEY, loadFeedbackPreference, saveFeedbackPreference,
} from '@/utils/feedback'

/** Provider 预设(与后端 PROVIDER_PRESETS 对齐,含 volcengine/longcat,F22)。 */
export const PROVIDER_PRESETS: Record<string, { label: string; baseUrl: string; models: string[] }> = {
  deepseek: {
    label: 'DeepSeek(深度求索)',
    baseUrl: 'https://api.deepseek.com',
    models: ['deepseek-v4-pro', 'deepseek-v4-flash', 'deepseek-chat'],
  },
  qwen: {
    label: '通义千问(阿里云)',
    baseUrl: 'https://dashscope.aliyuncs.com/compatible-mode/v1',
    models: ['qwen3-max', 'qwen3-plus', 'qwen3-turbo'],
  },
  glm: {
    label: '智谱 GLM',
    baseUrl: 'https://open.bigmodel.cn/api/paas/v4',
    models: ['glm-5.2', 'glm-5-turbo', 'glm-5-flash'],
  },
  kimi: {
    label: 'Kimi(月之暗面)',
    baseUrl: 'https://api.moonshot.cn',
    models: ['kimi-k2.6', 'kimi-k2-turbo'],
  },
  minimax: {
    label: 'MiniMax(稀宇科技)',
    baseUrl: 'https://api.minimaxi.com/v1',
    models: ['MiniMax-M3', 'MiniMax-M2'],
  },
  volcengine: {
    label: '火山引擎(字节跳动)',
    baseUrl: 'https://ark.cn-beijing.volces.com/api/v3',
    models: ['doubao-pro', 'doubao-lite', 'doubao-vision'],
  },
  longcat: {
    label: 'LongCat(美团)',
    baseUrl: 'https://api.longcat.cn/v1',
    models: ['longcat-pro', 'longcat-flash'],
  },
  anthropic: {
    label: 'Anthropic Claude',
    baseUrl: 'https://api.anthropic.com',
    models: ['claude-sonnet-5', 'claude-haiku-4-5-20251001'],
  },
  openai: {
    label: 'OpenAI',
    baseUrl: 'https://api.openai.com/v1',
    models: ['gpt-5.2', 'gpt-5.2-mini'],
  },
  ollama: {
    label: 'Ollama(本地)',
    baseUrl: 'http://localhost:11434',
    models: ['llama3.3', 'qwen3'],
  },
}

const NAME_KEY = 'thp_player_name'
const REBUY_KEY = 'thp_auto_rebuy'

/** 重购规则:缺省现金局(自动重购),仅显式存过 "false" 才用锦标赛。 */
function loadAutoRebuy(): boolean {
  return localStorage.getItem(REBUY_KEY) !== 'false'
}

export const useSettingsStore = defineStore('settings', {
  state: () => ({
    playerName: localStorage.getItem(NAME_KEY) ?? '玩家',
    startingChips: 1000,
    smallBlind: 5,
    bigBlind: 10,
    ante: 0,
    structure: 'no_limit' as BettingStructure,
    autoRebuy: loadAutoRebuy(),
    botConfigs: [
      { style: 'COOL' }, { style: 'BALANCED' }, { style: 'WARM' },
      { style: 'HOT' }, { style: 'CHAOS' },
    ] as BotConfig[],
    availableStyles: [] as BotStyleInfo[],
    deckSkin: loadPreferredSkin() as DeckSkin,
    soundEnabled: loadFeedbackPreference(SOUND_KEY),
    hapticsEnabled: loadFeedbackPreference(HAPTICS_KEY),
    llm: null as LlmConfigPayload | null,
    llmSaving: false,
  }),

  actions: {
    async loadStyles() {
      try {
        this.availableStyles = await fetchBotStyles()
      } catch { /* 服务器未起时静默,进入页面重试 */ }
    },

    async loadLlmConfig() {
      try {
        this.llm = await fetchLlmConfig()
      } catch { /* 同上 */ }
    },

    async saveLlm(): Promise<void> {
      if (!this.llm) return
      this.llmSaving = true
      try {
        await saveLlmConfig(this.llm)
      } finally {
        this.llmSaving = false
      }
    },

    /** 清除已存 API Key("" 语义,F23)。 */
    clearApiKey() {
      if (this.llm) this.llm.primary.api_key = ''
    },

    applyProviderPreset(provider: string) {
      if (!this.llm) return
      const preset = PROVIDER_PRESETS[provider]
      if (!preset) return
      this.llm.primary.provider = provider
      this.llm.primary.base_url = preset.baseUrl
      this.llm.primary.model = preset.models[0] ?? this.llm.primary.model
    },

    setDeckSkin(id: string) {
      const skin = DECK_SKINS.find((d) => d.id === id)
      if (skin) {
        this.deckSkin = skin
        savePreferredSkin(id)
      }
    },

    persistName() {
      localStorage.setItem(NAME_KEY, this.playerName)
    },

    setAutoRebuy(enabled: boolean) {
      this.autoRebuy = enabled
      localStorage.setItem(REBUY_KEY, String(enabled))
    },

    setSoundEnabled(enabled: boolean) {
      this.soundEnabled = enabled
      saveFeedbackPreference(SOUND_KEY, enabled)
    },

    setHapticsEnabled(enabled: boolean) {
      this.hapticsEnabled = enabled
      saveFeedbackPreference(HAPTICS_KEY, enabled)
    },
  },
})
