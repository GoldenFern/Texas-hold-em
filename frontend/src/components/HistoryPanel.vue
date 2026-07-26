<script setup lang="ts">
import { ref } from 'vue'
import { fetchStatsSummary } from '@/api/rest'
import { zh } from '@/i18n/zh'

type Stats = Awaited<ReturnType<typeof fetchStatsSummary>>

const stats = ref<Stats | null>(null)

async function refresh() {
  try {
    stats.value = await fetchStatsSummary()
  } catch {
    stats.value = null
  }
}

refresh()
defineExpose({ refresh })
</script>

<template>
  <div class="panel history scroll">
    <h3>
      {{ zh.panel.history }}
      <button class="mini" @click="refresh">{{ zh.llmDebug.refresh }}</button>
    </h3>
    <template v-if="stats && stats.player_stats.length">
      <div class="meta">共 {{ stats.total_hands }} 手</div>
      <table>
        <thead>
          <tr><th>玩家</th><th>手数</th><th>胜</th><th>VPIP</th><th>PFR</th><th>AF</th><th>盈亏</th></tr>
        </thead>
        <tbody>
          <tr v-for="p in stats.player_stats" :key="p.name">
            <td class="name">{{ p.name }}</td>
            <td>{{ p.hands_played }}</td>
            <td>{{ p.hands_won }}</td>
            <td>{{ (p.vpip * 100).toFixed(0) }}%</td>
            <td>{{ (p.pfr * 100).toFixed(0) }}%</td>
            <td>{{ p.aggression_factor.toFixed(1) }}</td>
            <td :class="p.profit >= 0 ? 'pos' : 'neg'">
              {{ p.profit >= 0 ? '+' : '' }}{{ p.profit }}
            </td>
          </tr>
        </tbody>
      </table>
    </template>
    <div v-else class="empty">—</div>
  </div>
</template>

<style scoped>
.history { font-size: .82rem; }
.mini { padding: 2px 8px; font-size: .75rem; margin-left: 8px; }
.meta { color: var(--text-dim); margin-bottom: 6px; }
table { width: 100%; border-collapse: collapse; }
th, td { text-align: right; padding: 4px 6px; border-bottom: 1px solid var(--border); }
th { color: var(--text-dim); font-weight: 500; }
td.name, th:first-child { text-align: left; }
.name { max-width: 110px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.pos { color: var(--green); }
.neg { color: var(--red); }
.empty { color: var(--text-dim); }
</style>
