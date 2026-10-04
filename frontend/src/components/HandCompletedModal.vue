<script setup lang="ts">
import { useGameStore } from '@/stores/game'
import { zh } from '@/i18n/zh'
import PokerCard from './PokerCard.vue'

const game = useGameStore()
</script>

<template>
  <Teleport to="body">
    <div v-if="game.handResult && !game.reviewingHand" class="overlay">
      <div class="modal panel">
        <h3>{{ zh.handResult.title }} · #{{ game.handResult.hand_id }}</h3>
        <div class="players scroll">
          <div
            v-for="p in game.handResult.players"
            :key="p.name"
            class="row"
            :class="{ winner: p.is_winner, folded: p.is_folded }"
          >
            <div class="who">
              <b>{{ p.name }}</b>
              <span class="profit" :class="p.net_profit >= 0 ? 'pos' : 'neg'">
                {{ p.net_profit >= 0 ? '+' : '' }}{{ p.net_profit }}
              </span>
            </div>
            <div class="cards">
              <PokerCard v-for="(c, i) in p.best_five" :key="i" :card="c" small
                         :dimmed="p.is_folded" />
            </div>
            <div class="desc">
              {{ p.is_folded ? zh.handResult.folded : (p.hand_description || zh.handResult.notShown) }}
            </div>
          </div>
        </div>
        <div v-if="game.handResult.decision_review" class="review" :class="game.handResult.decision_review.verdict">
          <div class="review-title">
            {{ zh.handResult.review }} · {{ game.handResult.decision_review.title }}
          </div>
          <div class="review-detail">{{ game.handResult.decision_review.detail }}</div>
          <div class="review-metrics">
            <span v-if="game.handResult.decision_review.equity != null">{{ zh.handResult.equity }} {{ game.handResult.decision_review.equity }}%</span>
            <span v-if="game.handResult.decision_review.required_equity != null">{{ zh.handResult.requiredEquity }} {{ game.handResult.decision_review.required_equity }}%</span>
            <span v-if="game.handResult.decision_review.ev != null">{{ zh.handResult.ev }} {{ game.handResult.decision_review.ev }}</span>
          </div>
        </div>
        <div class="footer">
          <button v-if="game.handResult.decision_review" @click="game.openReview(game.handResult.hand_id)">
            {{ zh.handResult.openReplay }}
          </button>
          <button class="primary" @click="game.continueGame()">{{ zh.panel.continue }}</button>
          <button class="danger" @click="game.endGame()">{{ zh.panel.endGame }}</button>
        </div>
      </div>
    </div>
  </Teleport>
</template>

<style scoped>
.overlay {
  position: fixed; inset: 0; background: rgba(5, 8, 12, .72);
  display: flex; align-items: center; justify-content: center; z-index: 50;
}
.modal { width: min(560px, 92vw); max-height: 84vh; display: flex; flex-direction: column; }
.players { display: flex; flex-direction: column; gap: 8px; overflow-y: auto; }
.row {
  display: grid; grid-template-columns: 130px 1fr 110px;
  gap: 8px; align-items: center;
  padding: 6px 8px; border-radius: 8px; background: var(--bg-panel-2);
}
.row.winner { outline: 1px solid var(--accent); }
.row.folded { opacity: .55; }
.who { display: flex; flex-direction: column; }
.profit.pos { color: var(--green); }
.profit.neg { color: var(--red); }
.cards { display: flex; gap: 4px; }
.desc { font-size: .8rem; color: var(--text-dim); text-align: right; }
.footer { display: flex; gap: 10px; justify-content: flex-end; margin-top: 12px; }
.review { margin-top: 10px; padding: 9px 10px; border-radius: 8px; background: rgba(216,166,66,.1); border: 1px solid rgba(216,166,66,.35); }
.review.review { border-color: rgba(216,166,66,.5); }
.review.review .review-title { color: var(--accent); }
.review.good_process { border-color: rgba(70,184,116,.45); }
.review.good_process .review-title { color: var(--green); }
.review-title { font-weight: 600; font-size: .86rem; }
.review-detail { margin-top: 3px; color: var(--text-dim); font-size: .78rem; }
.review-metrics { display: flex; gap: 12px; margin-top: 6px; color: var(--text-dim); font-size: .74rem; }

@media (max-width: 650px) {
  .overlay { align-items: flex-start; padding: 8px; overflow-y: auto; }
  .modal { width: 100%; max-height: none; padding: 10px; }
  .row { grid-template-columns: minmax(0, 1fr) auto; }
  .row .cards { grid-column: 1 / -1; grid-row: 2; }
  .row .desc { grid-column: 1 / -1; grid-row: 3; text-align: left; }
  .footer { flex-wrap: wrap; gap: 6px; }
  .footer button { flex: 1 1 0; min-width: 0; padding-inline: 6px; }
  .review-metrics { flex-wrap: wrap; gap: 4px 10px; }
}
</style>
