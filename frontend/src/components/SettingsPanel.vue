<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { useSettingsStore, PROVIDER_PRESETS } from '@/stores/settings'
import { useGameStore } from '@/stores/game'
import { useToastStore } from '@/stores/toast'
import { zh } from '@/i18n/zh'
import { DECK_SKINS } from '@/utils/deckSkin'
import type { BotConfig } from '@/api/protocol'

const settings = useSettingsStore()
const game = useGameStore()
const toast = useToastStore()

const botCount = ref(settings.botConfigs.length)

onMounted(() => {
  settings.loadStyles()
  settings.loadLlmConfig()
})

const styleOptions = computed(() =>
  settings.availableStyles.length
    ? settings.availableStyles
    : [
      { style: 'COLD', display_name: '极冷 T=0.03', description: '', temperature: 0.03 },
      { style: 'COOL', display_name: '偏冷 T=0.07', description: '', temperature: 0.07 },
      { style: 'BALANCED', display_name: '均衡 T=0.15', description: '', temperature: 0.15 },
      { style: 'WARM', display_name: '偏热 T=0.30', description: '', temperature: 0.30 },
      { style: 'HOT', display_name: '炎热 T=0.60', description: '', temperature: 0.60 },
      { style: 'CHAOS', display_name: '混沌 T=1.20', description: '', temperature: 1.20 },
      { style: 'LLM', display_name: 'LLM', description: '', temperature: 0.15 },
    ])

const rlcardNeedsHeadsUp = computed(() =>
  settings.botConfigs.length > 1
  && settings.botConfigs.some((b) => b.style === 'RLCARD'),
)

function syncBotCount() {
  const n = Math.max(1, Math.min(8, botCount.value))
  botCount.value = n
  const cfgs: BotConfig[] = [...settings.botConfigs]
  while (cfgs.length < n) cfgs.push({ style: 'BALANCED' })
  settings.botConfigs = cfgs.slice(0, n)
}

function startGame() {
  settings.persistName()
  game.newGame({
    player_name: settings.playerName || '玩家',
    bots: settings.botConfigs,
    starting_chips: settings.startingChips,
    small_blind: settings.smallBlind,
    big_blind: settings.bigBlind,
    ante: settings.ante,
    betting_structure: settings.structure,
    auto_rebuy: settings.autoRebuy,
  })
  // Prevent a hidden focused submit button from scrolling the mobile page.
  const active = document.activeElement
  if (active instanceof HTMLElement) active.blur()
  window.scrollTo(0, 0)
  document.querySelector('main')?.scrollTo(0, 0)
}

async function saveLlm() {
  try {
    await settings.saveLlm()
    toast.info(zh.settings.saved)
    await settings.loadLlmConfig()
  } catch (e) {
    toast.error(String(e instanceof Error ? e.message : e))
  }
}
</script>

<template>
  <div class="panel settings scroll">
    <h3>{{ zh.panel.newGame }}</h3>
    <div class="grid2">
      <div>
        <label>{{ zh.settings.playerName }}</label>
        <input v-model="settings.playerName" maxlength="20" />
      </div>
      <div>
        <label>{{ zh.settings.startingChips }}</label>
        <input type="number" v-model.number="settings.startingChips" min="100" step="100" />
      </div>
      <div>
        <label>{{ zh.settings.smallBlind }}</label>
        <input type="number" v-model.number="settings.smallBlind" min="1" />
      </div>
      <div>
        <label>{{ zh.settings.bigBlind }}</label>
        <input type="number" v-model.number="settings.bigBlind" min="2" />
      </div>
      <div>
        <label>{{ zh.settings.ante }}</label>
        <input type="number" v-model.number="settings.ante" min="0" />
      </div>
      <div>
        <label>{{ zh.settings.structure }}</label>
        <select v-model="settings.structure">
          <option value="no_limit">无限注</option>
          <option value="pot_limit">底池限注</option>
          <option value="fixed_limit">固定限注</option>
        </select>
      </div>
      <div>
        <label>{{ zh.settings.rebuyPolicy }}</label>
        <select
          :value="String(settings.autoRebuy)"
          @change="settings.setAutoRebuy(($event.target as HTMLSelectElement).value === 'true')"
        >
          <option value="true">{{ zh.settings.rebuyCash }}</option>
          <option value="false">{{ zh.settings.rebuyTournament }}</option>
        </select>
      </div>
      <div>
        <label>{{ zh.settings.botCount }}</label>
        <input type="number" v-model.number="botCount" min="1" max="8" @change="syncBotCount" />
      </div>
      <div>
        <label>{{ zh.settings.deckSkin }}</label>
        <select :value="settings.deckSkin.id" @change="settings.setDeckSkin(($event.target as HTMLSelectElement).value)">
          <option v-for="d in DECK_SKINS" :key="d.id" :value="d.id">{{ d.label }}</option>
        </select>
      </div>
      <label class="toggle"><input type="checkbox" :checked="settings.soundEnabled"
             @change="settings.setSoundEnabled(($event.target as HTMLInputElement).checked)" />
        {{ zh.settings.sound }}</label>
      <label class="toggle"><input type="checkbox" :checked="settings.hapticsEnabled"
             @change="settings.setHapticsEnabled(($event.target as HTMLInputElement).checked)" />
        {{ zh.settings.haptics }}</label>
    </div>

    <div class="bots">
      <div v-for="(bot, i) in settings.botConfigs" :key="i" class="bot-row">
        <span class="idx">#{{ i + 1 }}</span>
        <select v-model="bot.style">
          <option v-for="s in styleOptions" :key="s.style" :value="s.style">
            {{ s.display_name }}
          </option>
        </select>
      </div>
      <p v-if="rlcardNeedsHeadsUp" class="hint warn">{{ zh.settings.rlcardHeadsUp }}</p>
    </div>

    <button class="primary wide" @click="startGame">{{ zh.settings.start }}</button>

    <template v-if="settings.llm">
      <h3 class="llm-title">LLM</h3>
      <div class="grid2">
        <div>
          <label>{{ zh.settings.llmProvider }}</label>
          <select
            :value="settings.llm.primary.provider"
            @change="settings.applyProviderPreset(($event.target as HTMLSelectElement).value)"
          >
            <option v-for="(p, key) in PROVIDER_PRESETS" :key="key" :value="key">
              {{ p.label }}
            </option>
          </select>
        </div>
        <div>
          <label>{{ zh.settings.llmModel }}</label>
          <select v-model="settings.llm.primary.model">
            <option
              v-for="m in PROVIDER_PRESETS[settings.llm.primary.provider]?.models ?? [settings.llm.primary.model]"
              :key="m" :value="m"
            >{{ m }}</option>
          </select>
        </div>
        <div class="span2">
          <label>{{ zh.settings.llmApiKey }}</label>
          <div class="key-row">
            <input
              type="password" v-model="settings.llm.primary.api_key"
              :placeholder="zh.settings.llmApiKeyHint"
            />
            <button @click="settings.clearApiKey()">{{ zh.settings.llmClearKey }}</button>
          </div>
        </div>
        <div class="span2">
          <label>{{ zh.settings.llmBaseUrl }}</label>
          <input v-model="settings.llm.primary.base_url" />
        </div>
        <div>
          <label>{{ zh.settings.llmTimeout }}</label>
          <input type="number" v-model.number="settings.llm.primary.timeout_seconds" min="5" />
        </div>
        <div>
          <label>{{ zh.settings.llmTemperature }}</label>
          <input type="number" v-model.number="settings.llm.primary.temperature"
                 min="0" max="2" step="0.1" />
        </div>
        <div>
          <label>{{ zh.settings.llmReasoning }}</label>
          <select v-model="settings.llm.primary.reasoning_effort">
            <option value="disabled">关闭</option>
            <option value="high">高</option>
            <option value="max">最大</option>
          </select>
        </div>
      </div>
      <button class="wide" :disabled="settings.llmSaving" @click="saveLlm">
        {{ zh.settings.save }}
      </button>
    </template>
  </div>
</template>

<style scoped>
.settings { display: flex; flex-direction: column; gap: 12px; }
.grid2 { display: grid; grid-template-columns: 1fr 1fr; gap: 10px; }
.span2 { grid-column: span 2; }
.bots { display: flex; flex-direction: column; gap: 6px; }
.bot-row { display: flex; gap: 8px; align-items: center; }
.idx { color: var(--text-dim); width: 26px; }
.wide { width: 100%; }
.llm-title { margin-top: 8px; }
.key-row { display: flex; gap: 8px; }
.toggle { display: flex; gap: 6px; align-items: center; margin: 0; }
.toggle input { width: auto; accent-color: var(--accent); }
.hint { margin: 0; font-size: 12px; color: var(--text-dim); }
.hint.warn { color: var(--red); }
</style>
