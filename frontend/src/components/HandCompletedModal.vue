<script setup lang="ts">
import { useGameStore } from '@/stores/game'
import { zh } from '@/i18n/zh'
import PokerCard from './PokerCard.vue'

const game = useGameStore()
</script>

<template>
  <Teleport to="body">
    <div v-if="game.handResult" class="overlay">
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
        <div class="footer">
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
</style>
