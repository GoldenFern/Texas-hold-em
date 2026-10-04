<script setup lang="ts">
import { computed } from 'vue'
import type { PlayerState } from '@/api/protocol'
import { useGameStore } from '@/stores/game'
import { zh } from '@/i18n/zh'
import PokerCard from './PokerCard.vue'

const game = useGameStore()

const state = computed(() => game.state)

/** CSS 百分比椭圆座位坐标(F11:零 getBoundingClientRect,缩放天然自适应)。 */
function seatPosition(index: number, total: number): Record<string, string> {
  // 人类(seat 0)固定在正下方,其余按椭圆顺时针分布
  const angle = Math.PI / 2 + (2 * Math.PI * index) / total
  const left = 50 + (total >= 7 ? 49 : 46) * Math.cos(angle)
  const top = 50 + 44 * Math.sin(angle)
  const leftCount = Math.ceil((total - 1) / 2)
  const onLeft = index <= leftCount
  const columnCount = onLeft ? leftCount : total - 1 - leftCount
  const row = onLeft ? leftCount - index : index - leftCount - 1
  const portraitTop = columnCount > 1 ? 14 + 66 * row / (columnCount - 1) : 47
  return {
    '--seat-left': `${left}%`, '--seat-top': `${top}%`,
    '--mobile-left': `${50 + 42 * Math.cos(angle)}%`,
    '--mobile-top': `${50 + 40 * Math.sin(angle)}%`,
    '--portrait-left': index === 0 ? '50%' : onLeft ? '3%' : '97%',
    '--portrait-top': index === 0 ? '94%' : `${portraitTop}%`,
  }
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

const actionFeed = computed(() => [...game.actionFeed].slice(-6).reverse())

function actionText(action: string): string {
  return zh.actions[action.toLowerCase()] ?? action
}

function actionTime(timestamp: number): string {
  return new Date(timestamp).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', second: '2-digit' })
}
</script>

<template>
  <div class="table-wrap" :class="{
    'many-seats': seats.length >= 7,
    'crowded-seats': seats.length >= 4,
    'live-many-seats': seats.length >= 7 && state?.phase !== 'FINISHED',
  }">
    <div class="felt">
      <div class="board">
        <div class="pot" v-if="state">
          {{ zh.table.pot }}
          <Transition name="pot-pop" mode="out-in">
            <b :key="state.pot_total">${{ state.pot_total }}</b>
          </Transition>
          <span class="phase">{{ zh.phase[state.phase] ?? state.phase }} · #{{ state.hand_id }}</span>
        </div>
        <TransitionGroup name="card-deal" tag="div" class="community">
          <PokerCard v-for="(c, i) in communitySlots" :key="`${c || 'empty'}-${i}`" :card="c" />
        </TransitionGroup>
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
        :style="seat.pos"
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
          <span v-if="seat.player.current_bet > 0" :key="seat.player.current_bet" class="bet">下注 ${{ seat.player.current_bet }}</span>
          <span v-if="statusText(seat.player)" class="status">{{ statusText(seat.player) }}</span>
          <span v-if="seat.isThinking" class="thinking">
            {{ game.thinking?.isLlm ? zh.table.llmThinking : zh.table.thinking }}
          </span>
        </div>
      </div>
    </div>
    <div v-if="actionFeed.length" class="action-feed" aria-live="polite">
      <div class="feed-title">{{ zh.table.actionFeed }}</div>
      <TransitionGroup name="feed" tag="div" class="feed-list">
        <div v-for="item in actionFeed" :key="`${item.hand_id}-${item.action_index}`" class="feed-item">
          <span class="feed-time">{{ actionTime(item.occurred_at) }}</span>
          <span class="feed-phase">{{ zh.phase[item.phase] ?? item.phase }}</span>
          <b>{{ item.player }}</b>
          <span>{{ actionText(item.action) }}</span>
          <span v-if="item.amount > 0">${{ item.amount }}</span>
          <span v-if="item.is_all_in" class="all-in">{{ zh.actions.allIn }}</span>
        </div>
      </TransitionGroup>
    </div>
  </div>
</template>

<style scoped>
.table-wrap {
  position: relative; width: 100%; min-height: 500px;
  display: flex; flex-direction: column; gap: 8px;
}
.felt {
  position: relative; flex: 1 0 450px; min-height: 450px; margin: 24px 4% 60px;
  background: radial-gradient(ellipse at center, var(--felt) 0%, var(--felt-dark) 78%);
  border: 10px solid #3a2a1a;
  border-radius: 48% / 40%;
  box-shadow: inset 0 0 60px rgba(0,0,0,.45), 0 8px 30px rgba(0,0,0,.5);
}
.many-seats .felt { flex-basis: 480px; min-height: 480px; }
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
.card-deal-enter-active { transition: opacity .24s ease, transform .24s ease; }
.card-deal-enter-from { opacity: 0; transform: translateY(-18px) rotate(-4deg) scale(.9); }
.card-deal-leave-active { position: absolute; transition: opacity .16s ease; }
.card-deal-leave-to { opacity: 0; }
.pot-pop-enter-active, .pot-pop-leave-active { transition: opacity .18s, transform .18s; }
.pot-pop-enter-from { opacity: 0; transform: translateY(-4px) scale(1.08); }
.pot-pop-leave-to { opacity: 0; transform: translateY(4px); }
.action-feed {
  position: relative; flex-shrink: 0; width: 100%;
  padding: 7px 9px; border-radius: 8px; background: rgba(8, 13, 18, .72);
  border: 1px solid rgba(255,255,255,.12); font-size: .72rem; pointer-events: none;
}
.feed-title { color: var(--accent); margin-bottom: 4px; font-weight: 600; }
.feed-list { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 2px 12px; }
.feed-item { display: flex; gap: 5px; align-items: baseline; line-height: 1.45; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.feed-time { color: var(--text-dim); font-variant-numeric: tabular-nums; }
.feed-phase { color: var(--text-dim); }
.feed-item b { color: var(--text); }
.all-in { color: var(--accent); }
.feed-enter-active, .feed-leave-active { transition: opacity .18s, transform .18s; }
.feed-enter-from, .feed-leave-to { opacity: 0; transform: translateX(10px); }

.seat {
  position: absolute;
  left: var(--seat-left); top: var(--seat-top);
  transform: translate(-50%, -50%);
  display: flex; flex-direction: column; align-items: center; gap: 4px;
  min-width: 110px;
}
.seat-cards { display: flex; gap: 4px; }
.seat.human .seat-cards :deep(.card) { width: 72px; height: 102px; }
.seat.human .seat-cards :deep(.card-index) { font-size: 20px; }
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
.many-seats .seat-info { padding: 3px 8px; font-size: .75rem; line-height: 1.15; }
.seat.folded { opacity: .55; }
.name { font-weight: 600; white-space: nowrap; max-width: 150px; overflow: hidden; text-overflow: ellipsis; }
.chips { color: var(--accent); }
.bet { color: #ffd97a; }
.bet { animation: chip-hop .22s ease-out; }
.status { color: var(--text-dim); }
.thinking { color: var(--accent-2); animation: pulse 1.2s infinite; }
.chip {
  display: inline-block; font-size: .65rem; padding: 0 5px;
  border-radius: 8px; margin-right: 3px; vertical-align: 1px;
}
.chip.dealer { background: var(--accent); color: #221a06; }
.chip.blind { background: #40506a; }
@keyframes pulse { 50% { opacity: .35; } }
@keyframes chip-hop { from { opacity: .35; transform: translateY(-4px) scale(.95); } to { opacity: 1; transform: none; } }

@media (max-width: 650px) {
  .table-wrap {
    position: relative;
    display: flex;
    flex-direction: column;
    height: auto;
    min-height: 360px;
    gap: 0;
  }
  .felt {
    position: relative;
    inset: auto;
    flex: 0 0 420px;
    min-height: 420px;
    width: auto;
    height: 420px;
    margin: 22px 14px 24px;
  }
  .board { top: 46%; }
  .community :deep(.card) { width: 54px; height: 77px; }
  .action-feed {
    position: relative;
    right: auto;
    bottom: auto;
    width: auto;
    margin: 5px 0 0;
  }
  .feed-list { grid-template-columns: 1fr; }
  .seat {
    left: var(--mobile-left); top: var(--mobile-top);
    transform: translate(-50%, calc(-50% - 20px)); min-width: 95px;
  }
  .seat-cards { gap: 2px; }
  .seat-cards :deep(.card) { width: 36px; height: 51px; }
  .seat.human .seat-cards :deep(.card) { width: 52px; height: 74px; }
  .seat.human .seat-cards :deep(.card-index) { font-size: 19px; }
  .seat-info { min-width: 95px; padding: 3px 6px; font-size: .7rem; }

  .crowded-seats .felt { flex-basis: 540px; min-height: 540px; height: 540px; margin-top: 36px; }
  .live-many-seats .felt { flex-basis: 460px; min-height: 460px; height: 460px; }
  .crowded-seats .board { top: 46%; width: 178px; }
  .crowded-seats .pot { padding: 4px 8px; text-align: center; }
  .crowded-seats .pot .phase { display: block; margin-left: 0; }
  .crowded-seats .community { flex-wrap: wrap; justify-content: center; width: 178px; }

  .crowded-seats .seat {
    left: var(--portrait-left); top: var(--portrait-top);
    transform: translate(-50%, -50%); min-width: 78px; gap: 2px;
  }
  .crowded-seats .seat-cards { gap: 1px; }
  .crowded-seats .seat-info {
    display: block;
    min-width: 78px;
    max-width: 82px;
    padding: 2px 3px;
    font-size: .7rem;
    line-height: 1.25;
    text-align: center;
  }
  .crowded-seats .seat-info > span { display: inline; margin-right: 3px; }
  .crowded-seats .seat-info > span:last-child { margin-right: 0; }
  .crowded-seats .name { display: inline-block !important; max-width: 70px; vertical-align: bottom; }
  .crowded-seats .chip { font-size: .55rem; padding: 0 3px; }
  /* 手机多人桌仅突出自己的手牌和当前行动者的暗牌。 */
  .live-many-seats .seat:not(.human):not(.current) .seat-cards { display: none; }
}

@media (prefers-reduced-motion: reduce) {
  .card-deal-enter-active, .card-deal-leave-active, .pot-pop-enter-active, .pot-pop-leave-active,
  .feed-enter-active, .feed-leave-active { transition: none; }
  .thinking { animation: none; }
  .bet { animation: none; }
}
</style>
