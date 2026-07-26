<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { useGameStore } from '@/stores/game'
import { zh } from '@/i18n/zh'
import type { ActionName } from '@/api/protocol'

const game = useGameStore()

/** 滑块金额由本地持有;仅当合法区间变化时校正,不随无关广播重置(F2)。 */
const amount = ref(0)

const minRaise = computed(() => game.state?.min_raise ?? 0)
const maxBet = computed(() => game.state?.max_bet ?? 0)
const toCall = computed(() => game.state?.to_call ?? 0)

watch([minRaise, maxBet], ([lo, hi]) => {
  if (amount.value < lo || amount.value > hi) {
    amount.value = lo
  }
}, { immediate: true })

const legal = computed(() =>
  (game.state?.legal_actions ?? []).map((a) => a.toLowerCase() as ActionName))

const canAct = computed(() => game.isHumanTurn && !game.actionPending)

function has(a: ActionName): boolean {
  return legal.value.includes(a)
}

function act(a: ActionName) {
  if (!canAct.value) return
  const amt = a === 'bet' || a === 'raise' ? amount.value : 0
  game.sendAction(a, amt)
}

function allIn() {
  if (!canAct.value) return
  const a: ActionName = has('raise') ? 'raise' : 'bet'
  if (!has(a)) return
  game.sendAction(a, maxBet.value)
}

const betLabel = computed(() => has('bet') ? zh.actions.bet : zh.actions.raise)
</script>

<template>
  <div class="action-bar panel">
    <template v-if="game.isHumanTurn">
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
        <button v-if="has('bet') || has('raise')" :disabled="!canAct" @click="allIn">
          {{ zh.actions.allIn }} ${{ maxBet }}
        </button>
      </div>
      <div v-if="has('bet') || has('raise')" class="row slider">
        <input
          type="range" :min="minRaise" :max="maxBet" step="1"
          v-model.number="amount" :disabled="!canAct"
        />
        <input class="amount-input" type="number" :min="minRaise" :max="maxBet"
               v-model.number="amount" :disabled="!canAct" />
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
.action-bar { display: flex; flex-direction: column; gap: 10px; min-height: 92px; justify-content: center; }
.row.buttons { display: flex; gap: 10px; flex-wrap: wrap; }
.row.slider { display: flex; gap: 12px; align-items: center; }
.row.slider input[type="range"] { flex: 1; accent-color: var(--accent); }
.amount-input { width: 110px; }
.waiting { color: var(--text-dim); text-align: center; }
</style>
