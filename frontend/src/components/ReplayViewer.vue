<script setup lang="ts">
import { computed, onMounted } from 'vue'
import { useReplayStore } from '@/stores/replay'
import { useToastStore } from '@/stores/toast'
import { zh } from '@/i18n/zh'
import PokerCard from './PokerCard.vue'

const replay = useReplayStore()
const toast = useToastStore()

onMounted(() => {
  replay.loadList().catch(() => { /* 无对局时列表为空 */ })
})

async function open(handId: number) {
  try {
    await replay.open(handId)
  } catch (e) {
    toast.warn(String(e instanceof Error ? e.message : e))
  }
}

const snapshot = computed(() => replay.snapshot)

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
        <span class="step">
          {{ zh.replay.step }} {{ replay.stepIndex }}/{{ replay.maxStep }}
          · {{ snapshot.phase }}
        </span>
        <button @click="replay.next()" :disabled="replay.stepIndex >= replay.maxStep">
          {{ zh.replay.next }} →
        </button>
        <button class="danger" @click="replay.close()">{{ zh.replay.exit }}</button>
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
.action-line { color: var(--accent); }
.board-line, .prow { display: flex; gap: 8px; align-items: center; }
.cards { display: inline-flex; gap: 3px; }
.players { display: flex; flex-direction: column; gap: 4px; }
.prow.folded { opacity: .5; }
.pname { width: 110px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.bet { color: #ffd97a; }
.winners-line { color: var(--green); }
</style>
