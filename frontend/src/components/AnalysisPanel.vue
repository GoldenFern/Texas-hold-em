<script setup lang="ts">
import { computed } from 'vue'
import { useGameStore } from '@/stores/game'
import { zh } from '@/i18n/zh'

const game = useGameStore()
const analysis = computed(() => game.analysis)

const topHandTypes = computed(() => {
  const probs = analysis.value?.hand_type_probs ?? {}
  return Object.entries(probs).filter(([, v]) => v > 0).slice(0, 6)
})

const rankingEntries = computed(() =>
  (analysis.value?.ranking_distribution ?? []).filter((e) => e.rank >= 1))
</script>

<template>
  <div class="panel analysis scroll">
    <h3>{{ zh.analysis.title }}</h3>
    <template v-if="analysis">
      <div class="decision-card">
        <div class="decision-heading">{{ zh.analysis.currentDecision }}</div>
        <div class="decision-main">
          <span>{{ zh.analysis.equity }}</span>
          <b>{{ analysis.odds_ev.equity }}% <small v-if="analysis.odds_ev.ci_95">±{{ analysis.odds_ev.ci_95 }}</small></b>
        </div>
        <div class="decision-grid">
          <span>{{ zh.analysis.requiredEquity }} <b v-if="analysis.odds_ev.has_call_decision">{{ analysis.odds_ev.required_equity }}%</b><b v-else>—</b></span>
          <span>{{ zh.analysis.potOdds }} <b v-if="analysis.odds_ev.has_call_decision">{{ analysis.odds_ev.pot_odds_ratio }}:1</b><b v-else>—</b></span>
          <span>{{ zh.analysis.toCall }} <b>${{ analysis.odds_ev.to_call }}</b></span>
          <span>{{ zh.analysis.ev }} <b :class="analysis.odds_ev.ev >= 0 ? 'pos' : 'neg'">{{ analysis.odds_ev.ev >= 0 ? '+' : '' }}{{ analysis.odds_ev.ev }}</b></span>
        </div>
        <div class="judgment">{{ analysis.odds_ev.ev_judgment }}</div>
      </div>
      <div class="kv">
        <span>{{ zh.analysis.winRate }}</span>
        <b>{{ analysis.odds_ev.win_rate }}%</b>
      </div>
      <details class="advanced">
        <summary>{{ zh.analysis.details }}</summary>
        <h3 class="sub">{{ zh.analysis.handTypes }}</h3>
        <div v-for="[name, prob] in topHandTypes" :key="name" class="bar-row">
          <span class="bar-label">{{ name }}</span>
          <div class="bar"><div class="fill" :style="{ width: `${Math.min(100, prob)}%` }" /></div>
          <span class="bar-val">{{ prob }}%</span>
        </div>

        <h3 class="sub">{{ zh.analysis.ranking }}</h3>
        <div v-for="e in rankingEntries" :key="e.rank" class="bar-row">
          <span class="bar-label">{{ e.desc }}</span>
          <div class="bar"><div class="fill alt" :style="{ width: `${Math.min(100, e.prob)}%` }" /></div>
          <span class="bar-val">{{ e.prob }}%</span>
        </div>
      </details>

      <div class="foot">
        {{ zh.analysis.deadMoney }} ${{ analysis.pot_financials.dead_money }}
        · {{ zh.analysis.sunkCost }} ${{ analysis.pot_financials.sunk_cost }}
        · {{ zh.analysis.simCount }} {{ analysis.sim_count }}
      </div>
    </template>
    <div v-else class="empty">—</div>
  </div>
</template>

<style scoped>
.analysis { font-size: .85rem; }
.decision-card { padding: 10px; margin-bottom: 8px; border-radius: 8px; background: linear-gradient(135deg, rgba(78,154,241,.14), rgba(216,166,66,.1)); border: 1px solid rgba(78,154,241,.35); }
.decision-heading { color: var(--accent); font-size: .75rem; text-transform: uppercase; letter-spacing: .04em; }
.decision-main { display: flex; justify-content: space-between; align-items: baseline; margin: 4px 0 8px; }
.decision-main b { font-size: 1.2rem; }
.decision-main small { color: var(--text-dim); font-size: .72rem; font-weight: 400; }
.decision-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 4px 12px; color: var(--text-dim); font-size: .76rem; }
.decision-grid b { color: var(--text); }
.kv { display: flex; justify-content: space-between; padding: 2px 0; }
.kv small { color: var(--text-dim); font-weight: 400; }
.pos { color: var(--green); }
.neg { color: var(--red); }
.judgment { color: var(--text-dim); margin: 4px 0 8px; font-size: .8rem; }
.advanced { margin-top: 10px; }
.advanced summary { cursor: pointer; color: var(--text-dim); font-size: .8rem; }
.sub { margin-top: 12px; font-size: .85rem; }
.bar-row { display: grid; grid-template-columns: 64px 1fr 48px; gap: 6px; align-items: center; padding: 1px 0; }
.bar-label { color: var(--text-dim); font-size: .75rem; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.bar { background: #10151c; border-radius: 4px; height: 10px; overflow: hidden; }
.fill { background: var(--accent); height: 100%; }
.fill.alt { background: var(--accent-2); }
.bar-val { text-align: right; font-size: .75rem; }
.foot { margin-top: 10px; color: var(--text-dim); font-size: .72rem; }
.empty { color: var(--text-dim); }
</style>
