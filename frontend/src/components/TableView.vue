<script setup lang="ts">
import { computed } from 'vue'
import type { PlayerState } from '@/api/protocol'
import { useGameStore } from '@/stores/game'
import { zh } from '@/i18n/zh'
import PokerCard from './PokerCard.vue'

const game = useGameStore()

const state = computed(() => game.state)

/** CSS 百分比椭圆座位坐标(F11:零 getBoundingClientRect,缩放天然自适应)。 */
function seatPosition(index: number, total: number): { left: string; top: string } {
  // 人类(seat 0)固定在正下方,其余按椭圆顺时针分布
  const angle = Math.PI / 2 + (2 * Math.PI * index) / total
  const left = 50 + 42 * Math.cos(angle)
  const top = 50 + 40 * Math.sin(angle)
  return { left: `${left}%`, top: `${top}%` }
}

const seats = computed(() => {
  const s = state.value
  if (!s) return []
  return s.players.map((p, i) => ({
    player: p,
    pos: seatPosition(i, s.players.length),
    isCurrent: i === s.current_player_index && s.phase !== 'FINISHED',
    isThinking: game.thinking?.player === p.name,
  }))
})

function statusText(p: PlayerState): string {
  return zh.status[p.status] ?? ''
}

const communitySlots = computed(() => {
  const cc = state.value?.community_cards ?? []
  return [...cc, ...Array(Math.max(0, 5 - cc.length)).fill('')]
})
</script>

<template>
  <div class="table-wrap">
    <div class="felt">
      <div class="board">
        <div class="pot" v-if="state">
          {{ zh.table.pot }} <b>${{ state.pot_total }}</b>
          <span class="phase">{{ zh.phase[state.phase] ?? state.phase }} · #{{ state.hand_id }}</span>
        </div>
        <div class="community">
          <PokerCard v-for="(c, i) in communitySlots" :key="i" :card="c" />
        </div>
      </div>

      <div
        v-for="seat in seats"
        :key="seat.player.seat"
        class="seat"
        :class="{
          current: seat.isCurrent,
          folded: seat.player.status === 'FOLDED' || seat.player.status === 'OUT',
          human: seat.player.is_human,
        }"
        :style="{ left: seat.pos.left, top: seat.pos.top }"
      >
        <div class="seat-cards">
          <PokerCard
            v-for="(c, i) in seat.player.hole_cards"
            :key="i"
            :card="c"
            small
            :dimmed="seat.player.status === 'FOLDED'"
          />
        </div>
        <div class="seat-info">
          <span class="name">
            <span v-if="seat.player.is_dealer" class="chip dealer">{{ zh.table.dealer }}</span>
            <span v-else-if="seat.player.is_small_blind" class="chip blind">{{ zh.table.smallBlind }}</span>
            <span v-else-if="seat.player.is_big_blind" class="chip blind">{{ zh.table.bigBlind }}</span>
            {{ seat.player.name }}
          </span>
          <span class="chips">${{ seat.player.chips }}</span>
          <span v-if="seat.player.current_bet > 0" class="bet">下注 ${{ seat.player.current_bet }}</span>
          <span v-if="statusText(seat.player)" class="status">{{ statusText(seat.player) }}</span>
          <span v-if="seat.isThinking" class="thinking">
            {{ game.thinking?.isLlm ? zh.table.llmThinking : zh.table.thinking }}
          </span>
        </div>
      </div>
    </div>
  </div>
</template>

<style scoped>
.table-wrap { position: relative; width: 100%; height: 100%; min-height: 460px; }
.felt {
  position: absolute; inset: 6% 4%;
  background: radial-gradient(ellipse at center, var(--felt) 0%, var(--felt-dark) 78%);
  border: 10px solid #3a2a1a;
  border-radius: 48% / 40%;
  box-shadow: inset 0 0 60px rgba(0,0,0,.45), 0 8px 30px rgba(0,0,0,.5);
}
.board {
  position: absolute; left: 50%; top: 50%;
  transform: translate(-50%, -50%);
  display: flex; flex-direction: column; align-items: center; gap: 10px;
}
.pot {
  color: #f4e9c8; background: rgba(0,0,0,.35);
  padding: 4px 14px; border-radius: 20px; font-size: .9rem;
}
.pot .phase { margin-left: 10px; color: var(--text-dim); font-size: .8rem; }
.community { display: flex; gap: 8px; }

.seat {
  position: absolute;
  transform: translate(-50%, -50%);
  display: flex; flex-direction: column; align-items: center; gap: 4px;
  min-width: 110px;
}
.seat-cards { display: flex; gap: 4px; }
.seat-info {
  background: rgba(10, 14, 19, .82);
  border: 1px solid var(--border);
  border-radius: 8px;
  padding: 4px 10px;
  display: flex; flex-direction: column; align-items: center;
  font-size: .8rem; line-height: 1.35;
  min-width: 110px;
}
.seat.current .seat-info { border-color: var(--accent); box-shadow: 0 0 12px rgba(216,166,66,.5); }
.seat.human .seat-info { border-color: var(--accent-2); }
.seat.folded { opacity: .55; }
.name { font-weight: 600; white-space: nowrap; max-width: 150px; overflow: hidden; text-overflow: ellipsis; }
.chips { color: var(--accent); }
.bet { color: #ffd97a; }
.status { color: var(--text-dim); }
.thinking { color: var(--accent-2); animation: pulse 1.2s infinite; }
.chip {
  display: inline-block; font-size: .65rem; padding: 0 5px;
  border-radius: 8px; margin-right: 3px; vertical-align: 1px;
}
.chip.dealer { background: var(--accent); color: #221a06; }
.chip.blind { background: #40506a; }
@keyframes pulse { 50% { opacity: .35; } }
</style>
