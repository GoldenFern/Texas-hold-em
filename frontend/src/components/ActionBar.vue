<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { useGameStore } from '@/stores/game'
import { useSettingsStore } from '@/stores/settings'
import { useReplayStore } from '@/stores/replay'
import { zh } from '@/i18n/zh'
import type { ActionName } from '@/api/protocol'
import { playActionCue, triggerActionHaptic } from '@/utils/feedback'
import { potFractionAmount } from '@/utils/betSizing'

const game = useGameStore()
const settings = useSettingsStore()
const replay = useReplayStore()

/** 滑块金额由本地持有;仅当合法区间变化时校正,不随无关广播重置(F2)。 */
const amount = ref(0)

const minRaise = computed(() => game.state?.min_raise ?? 0)
const maxBet = computed(() => game.state?.max_bet ?? 0)
const toCall = computed(() => game.state?.to_call ?? 0)
const potTotal = computed(() => game.state?.pot_total ?? 0)
const currentBet = computed(() => game.humanPlayer?.current_bet ?? 0)
const maximumLabel = computed(() => maxBet.value >= currentBet.value + (game.humanPlayer?.chips ?? 0)
  ? zh.actions.allIn : zh.table.maximumBet)
const now = ref(Date.now())
let countdownTimer: number | undefined

watch([minRaise, maxBet], ([lo, hi]) => {
  if (amount.value < lo || amount.value > hi) {
    amount.value = lo
  }
}, { immediate: true })

const legal = computed(() =>
  (game.state?.legal_actions ?? []).map((a) => a.toLowerCase() as ActionName))

const canAct = computed(() => game.isHumanTurn && !game.actionPending)

const remainingMs = computed(() => {
  const deadline = game.actionDeadlineAt
  if (deadline == null) return game.isHumanTurn ? game.actionTimeout * 1000 : 0
  return Math.max(0, deadline - now.value)
})
const remainingSeconds = computed(() => Math.ceil(remainingMs.value / 1000))
const countdownPercent = computed(() => {
  const total = Math.max(1, game.actionTimeout * 1000)
  return Math.min(100, Math.max(0, remainingMs.value / total * 100))
})
const lowTime = computed(() => remainingSeconds.value <= 10 && remainingSeconds.value > 0)

const analysis = computed(() => game.analysis)
const requiredEquity = computed(() => {
  if (analysis.value && !analysis.value.odds_ev.has_call_decision && toCall.value <= 0) return null
  const fromAnalysis = analysis.value?.odds_ev.required_equity
  if (fromAnalysis != null) return fromAnalysis
  if (toCall.value <= 0) return null
  return Math.round(toCall.value / Math.max(1, potTotal.value + toCall.value) * 100 * 10) / 10
})
const potOdds = computed(() => analysis.value?.odds_ev.pot_odds_ratio ?? null)

function has(a: ActionName): boolean {
  return legal.value.includes(a)
}

function act(a: ActionName) {
  if (!canAct.value) return
  const amt = a === 'bet' || a === 'raise' ? amount.value : 0
  playActionCue(settings.soundEnabled)
  triggerActionHaptic(settings.hapticsEnabled)
  game.sendAction(a, amt)
}

function betMaximum() {
  if (!canAct.value) return
  const a: ActionName = has('raise') ? 'raise' : 'bet'
  if (!has(a)) return
  playActionCue(settings.soundEnabled)
  triggerActionHaptic(settings.hapticsEnabled)
  game.sendAction(a, maxBet.value)
}

function setAmount(value: number) {
  amount.value = Math.round(Math.max(minRaise.value, Math.min(maxBet.value, value)))
}

function setFraction(fraction: number) {
  setAmount(potFractionAmount({
    currentBet: currentBet.value, toCall: toCall.value, potTotal: potTotal.value,
    minBet: minRaise.value, maxBet: maxBet.value,
  }, fraction))
}

function handleKeydown(event: KeyboardEvent) {
  const target = event.target as HTMLElement | null
  if (
    target?.matches('input, select, textarea, [contenteditable="true"]')
    || !canAct.value
    || replay.active
  ) return
  const key = event.key.toLowerCase()
  if (key === '1') setFraction(.5)
  else if (key === '2') setFraction(.75)
  else if (key === 'p') setFraction(1)
  else if (key === 'm') betMaximum()
  else if (key === 'f' && has('fold')) act('fold')
  else if (key === 'c' && has('call')) act('call')
  else if (key === 'x' && has('check')) act('check')
  else return
  event.preventDefault()
}

onMounted(() => {
  countdownTimer = window.setInterval(() => { now.value = Date.now() }, 100)
  window.addEventListener('keydown', handleKeydown)
})

onBeforeUnmount(() => {
  if (countdownTimer !== undefined) window.clearInterval(countdownTimer)
  window.removeEventListener('keydown', handleKeydown)
})

const betLabel = computed(() => has('bet') ? zh.actions.bet : zh.actions.raise)
</script>

<template>
  <div class="action-bar panel" :class="{ 'low-time': lowTime }">
    <template v-if="game.isHumanTurn">
      <div class="action-meta">
        <span class="turn-label">{{ zh.table.yourTurn }}</span>
        <span class="countdown" :class="{ warning: lowTime }" role="timer"
              :aria-label="`${zh.table.timeLeft} ${remainingSeconds} ${zh.table.seconds}`">
          {{ remainingSeconds }}s
        </span>
      </div>
      <div class="timer-track" aria-hidden="true">
        <div class="timer-fill" :style="{ width: `${countdownPercent}%` }" />
      </div>
      <div class="row buttons">
        <button v-if="has('fold')" class="danger" :disabled="!canAct" @click="act('fold')">
          {{ zh.actions.fold }}
        </button>
        <button v-if="has('check')" :disabled="!canAct" @click="act('check')">
          {{ zh.actions.check }}
        </button>
        <button v-if="has('call')" class="primary" :disabled="!canAct" @click="act('call')">
          {{ zh.actions.call }} ${{ toCall }}
        </button>
        <button
          v-if="has('bet') || has('raise')"
          class="primary" :disabled="!canAct"
          @click="act(has('bet') ? 'bet' : 'raise')"
        >
          {{ betLabel }} ${{ amount }}
        </button>
        <button v-if="has('bet') || has('raise')" :disabled="!canAct" @click="betMaximum">
          {{ maximumLabel }} ${{ maxBet }}
        </button>
      </div>
      <div v-if="has('bet') || has('raise')" class="row slider">
        <input
          type="range" :min="minRaise" :max="maxBet" step="1"
          v-model.number="amount" :disabled="!canAct"
          :aria-label="zh.table.betAmount"
          :aria-valuetext="`${zh.table.betAmount} ${amount}, ${zh.table.range} ${minRaise}-${maxBet}`"
        />
        <input class="amount-input" type="number" :min="minRaise" :max="maxBet"
               v-model.number="amount" :disabled="!canAct"
               :aria-label="zh.table.betAmount" />
      </div>
      <div v-if="has('bet') || has('raise')" class="row presets" :aria-label="zh.table.betPresets">
        <button type="button" :disabled="!canAct" @click="setFraction(.5)">
          ½ {{ zh.table.pot }}
        </button>
        <button type="button" :disabled="!canAct" @click="setFraction(.75)">
          ¾ {{ zh.table.pot }}
        </button>
        <button type="button" :disabled="!canAct" @click="setFraction(1)">
          {{ zh.table.pot }}
        </button>
        <button type="button" :disabled="!canAct" @click="betMaximum">
          {{ maximumLabel }}
        </button>
      </div>
      <div class="decision-context" v-if="toCall > 0 || requiredEquity != null">
        <span>{{ zh.analysis.potOdds }} <b v-if="potOdds != null">{{ potOdds }}:1</b><b v-else>—</b></span>
        <span>{{ zh.analysis.requiredEquity }} <b v-if="requiredEquity != null">{{ requiredEquity }}%</b><b v-else>—</b></span>
        <span v-if="toCall > 0">{{ zh.actions.call }} ${{ toCall }}</span>
      </div>
    </template>
    <div v-else class="waiting">
      <span v-if="game.thinking">
        {{ game.thinking.player }} {{ game.thinking.isLlm ? zh.table.llmThinking : zh.table.thinking }}
      </span>
      <span v-else-if="game.gameStarted">{{ zh.table.waiting }}</span>
    </div>
  </div>
</template>

<style scoped>
.action-bar { display: flex; flex-direction: column; gap: 10px; min-height: 220px; justify-content: center; }
.action-meta { display: flex; justify-content: space-between; align-items: center; }
.turn-label { color: var(--accent); font-weight: 600; }
.countdown { font-variant-numeric: tabular-nums; color: var(--text-dim); }
.countdown.warning { color: var(--red); font-weight: 700; animation: pulse 1s infinite; }
.timer-track { height: 4px; border-radius: 4px; background: #10151c; overflow: hidden; }
.timer-fill { height: 100%; background: var(--accent-2); transition: width .1s linear, background .2s; }
.low-time .timer-fill { background: var(--red); }
.row.buttons { display: flex; gap: 10px; flex-wrap: wrap; }
.row.slider { display: flex; gap: 12px; align-items: center; }
.row.slider input[type="range"] { flex: 1; accent-color: var(--accent); }
.amount-input { width: 110px; }
.row.presets { display: flex; gap: 6px; flex-wrap: wrap; }
.row.presets button { padding: 4px 9px; font-size: .78rem; }
.decision-context { display: flex; gap: 14px; flex-wrap: wrap; color: var(--text-dim); font-size: .76rem; }
.decision-context b { color: var(--text); }
.waiting { color: var(--text-dim); text-align: center; }
@keyframes pulse { 50% { opacity: .45; } }

@media (max-width: 520px) {
  .action-bar { min-height: 264px; }
  .row.buttons { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 6px; }
  .row.buttons button { min-width: 0; padding-inline: 5px; }
}

@media (prefers-reduced-motion: reduce) {
  .countdown.warning { animation: none; }
  .timer-fill { transition: none; }
}
</style>
