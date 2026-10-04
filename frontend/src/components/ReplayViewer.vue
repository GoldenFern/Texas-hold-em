<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, watch } from 'vue'
import { useReplayStore } from '@/stores/replay'
import { useToastStore } from '@/stores/toast'
import { useGameStore } from '@/stores/game'
import { zh } from '@/i18n/zh'
import PokerCard from './PokerCard.vue'

const replay = useReplayStore()
const toast = useToastStore()
const game = useGameStore()

onMounted(async () => {
  await replay.loadList().catch(() => { /* 无对局时列表为空 */ })
  if (game.reviewHandId != null) {
    await open(game.reviewHandId, true)
    game.clearReviewRequest()
  }
  window.addEventListener('keydown', handleKeydown)
})

onBeforeUnmount(() => {
  replay.pause()
  window.removeEventListener('keydown', handleKeydown)
})

async function open(handId: number, focusReview = false) {
  try {
    await replay.open(handId)
    if (focusReview && replay.current?.decision_review) {
      replay.jumpTo(replay.current.decision_review.action_index + 1)
    }
  } catch (e) {
    toast.warn(String(e instanceof Error ? e.message : e))
    if (focusReview) game.exitReview()
  }
}

function closeViewer() {
  replay.close()
  if (game.reviewingHand) game.exitReview()
}

function continueFromReview() {
  replay.close()
  game.continueGame()
}

function endFromReview() {
  replay.close()
  game.endGame()
}

watch(() => game.reviewHandId, (handId) => {
  if (handId == null || !replay.active) return
  open(handId, true).finally(() => game.clearReviewRequest())
})

const snapshot = computed(() => replay.snapshot)
const phaseStops = computed(() => replay.phaseStops)

function setSpeedFromEvent(event: Event) {
  replay.setSpeed(Number((event.target as HTMLSelectElement).value))
}

function phaseEnd(step: number): number {
  return phaseStops.value.find((next) => next.step > step)?.step ?? replay.maxStep + 1
}

function handleKeydown(event: KeyboardEvent) {
  if (!replay.active) return
  const target = event.target as HTMLElement | null
  if (target?.matches('input, select, textarea, [contenteditable="true"]')) return
  if (event.key === 'ArrowLeft') replay.prev()
  else if (event.key === 'ArrowRight') replay.next()
  else if (event.key === ' ') replay.togglePlay()
  else if (event.key === 'Home') replay.jumpTo(0)
  else if (event.key === 'End') replay.jumpTo(replay.maxStep)
  else return
  event.preventDefault()
}

function winnersText(w: Record<string, number>): string {
  return Object.entries(w).map(([n, a]) => `${n} +$${a}`).join(', ')
}
</script>

<template>
  <div class="panel replay scroll">
    <h3>{{ zh.panel.replay }}</h3>

    <template v-if="!replay.active">
      <div v-if="replay.list.length === 0" class="empty">{{ zh.replay.empty }}</div>
      <div
        v-for="r in [...replay.list].reverse()"
        :key="r.hand_id"
        class="item"
        @click="open(r.hand_id)"
      >
        <b>#{{ r.hand_id }}</b>
        <span class="dim">{{ zh.replay.pot }} ${{ r.pot_total }}</span>
        <span class="winners">{{ winnersText(r.winners) }}</span>
      </div>
    </template>

    <template v-else-if="replay.current && snapshot">
      <div class="controls">
        <button @click="replay.prev()" :disabled="replay.stepIndex === 0">
          ← {{ zh.replay.prev }}
        </button>
        <button class="primary" @click="replay.togglePlay()">
          {{ replay.playing ? zh.replay.pause : zh.replay.play }}
        </button>
        <span class="step">
          {{ zh.replay.step }} {{ replay.stepIndex }}/{{ replay.maxStep }}
          · {{ zh.phase[snapshot.phase] ?? snapshot.phase }}
        </span>
        <button @click="replay.next()" :disabled="replay.stepIndex >= replay.maxStep">
          {{ zh.replay.next }} →
        </button>
        <button class="danger" @click="closeViewer">{{ zh.replay.exit }}</button>
      </div>

      <div class="timeline">
        <input type="range" min="0" :max="replay.maxStep" step="1"
               v-model.number="replay.stepIndex" @input="replay.pause()"
               :aria-label="zh.replay.step" />
        <label>{{ zh.replay.speed }}
          <select :value="replay.speed" @change="setSpeedFromEvent">
            <option :value="0.5">0.5×</option>
            <option :value="1">1×</option>
            <option :value="1.5">1.5×</option>
            <option :value="2">2×</option>
          </select>
        </label>
      </div>

      <div class="phase-jumps" :aria-label="zh.replay.phases">
        <span class="dim">{{ zh.replay.phases }}</span>
        <button v-for="stop in phaseStops" :key="`${stop.phase}-${stop.step}`"
                :class="{ active: replay.stepIndex >= stop.step && replay.stepIndex < phaseEnd(stop.step) }"
                @click="replay.jumpTo(stop.step)">
          {{ zh.phase[stop.phase] ?? stop.phase }}
        </button>
      </div>

      <div class="action-line" v-if="replay.currentAction">
        {{ replay.currentAction.player }}:
        {{ zh.actions[replay.currentAction.action.toLowerCase()] ?? replay.currentAction.action }}
        <template v-if="replay.currentAction.amount > 0">${{ replay.currentAction.amount }}</template>
        <template v-if="replay.currentAction.is_all_in">（{{ zh.actions.allIn }}）</template>
      </div>

      <div class="board-line">
        {{ zh.replay.pot }} ${{ snapshot.pot_total }}
        <span class="cards">
          <PokerCard v-for="(c, i) in snapshot.community_cards" :key="i" :card="c" small />
        </span>
      </div>

      <div class="players">
        <div v-for="p in snapshot.players" :key="p.name" class="prow"
             :class="{ folded: p.status === 'FOLDED' || p.status === 'OUT' }">
          <span class="pname">
            <template v-if="p.is_dealer">🔘</template>{{ p.name }}
          </span>
          <span class="cards">
            <PokerCard v-for="(c, i) in p.hole_cards" :key="i" :card="c" small />
          </span>
          <span class="dim">${{ p.chips }}</span>
          <span v-if="p.current_bet > 0" class="bet">-${{ p.current_bet }}</span>
        </div>
      </div>

      <div class="winners-line" v-if="replay.stepIndex === replay.maxStep">
        {{ zh.replay.winners }}: {{ winnersText(replay.current.winners) }}
      </div>
      <div v-if="replay.current.decision_review" class="review-line">
        <b>{{ zh.replay.review }} · {{ replay.current.decision_review.title }}</b>
        <span>{{ replay.current.decision_review.detail }}</span>
      </div>
      <div v-if="game.reviewingHand" class="review-actions">
        <button class="primary" @click="continueFromReview">{{ zh.panel.continue }}</button>
        <button class="danger" @click="endFromReview">{{ zh.panel.endGame }}</button>
      </div>
    </template>
  </div>
</template>

<style scoped>
.replay { font-size: .85rem; display: flex; flex-direction: column; gap: 8px; }
.empty, .dim { color: var(--text-dim); }
.item {
  display: flex; gap: 10px; align-items: baseline; padding: 6px 8px;
  border-radius: 6px; background: var(--bg-panel-2); cursor: pointer;
}
.item:hover { outline: 1px solid var(--border); }
.winners { color: var(--green); font-size: .78rem; margin-left: auto; }
.controls { display: flex; gap: 8px; align-items: center; flex-wrap: wrap; }
.controls .step { color: var(--text-dim); }
.timeline { display: flex; gap: 12px; align-items: center; }
.timeline input[type="range"] { flex: 1; accent-color: var(--accent); }
.timeline label { display: flex; align-items: center; gap: 5px; margin: 0; white-space: nowrap; }
.timeline select { width: auto; padding: 4px 6px; }
.phase-jumps { display: flex; gap: 5px; align-items: center; flex-wrap: wrap; }
.phase-jumps button { padding: 3px 7px; font-size: .72rem; }
.phase-jumps button.active { border-color: var(--accent); color: var(--accent); }
.action-line { color: var(--accent); }
.board-line, .prow { display: flex; gap: 8px; align-items: center; }
.board-line { flex-wrap: wrap; }
.cards { display: inline-flex; gap: 3px; }
.players { display: flex; flex-direction: column; gap: 4px; }
.prow.folded { opacity: .5; }
.pname { width: 110px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.bet { color: #ffd97a; }
.winners-line { color: var(--green); }
.review-line { display: flex; flex-direction: column; gap: 3px; padding: 8px; border-radius: 7px; background: rgba(216,166,66,.1); color: var(--text-dim); }
.review-line b { color: var(--accent); }
.review-actions { display: flex; gap: 8px; justify-content: flex-end; }

@media (max-width: 650px) {
  .prow { display: grid; grid-template-columns: minmax(0, 1fr) auto; }
  .pname { width: auto; }
  .prow .bet { text-align: right; }
}
</style>
