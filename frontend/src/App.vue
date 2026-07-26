<script setup lang="ts">
import { onMounted, ref, watch } from 'vue'
import { useGameStore } from '@/stores/game'
import { zh } from '@/i18n/zh'
import TableView from '@/components/TableView.vue'
import ActionBar from '@/components/ActionBar.vue'
import AnalysisPanel from '@/components/AnalysisPanel.vue'
import SettingsPanel from '@/components/SettingsPanel.vue'
import ReplayViewer from '@/components/ReplayViewer.vue'
import LlmDebugPanel from '@/components/LlmDebugPanel.vue'
import HistoryPanel from '@/components/HistoryPanel.vue'
import HandCompletedModal from '@/components/HandCompletedModal.vue'
import ToastHost from '@/components/ToastHost.vue'

type Tab = 'settings' | 'analysis' | 'history' | 'replay' | 'llm'

const game = useGameStore()
const tab = ref<Tab>('settings')

onMounted(() => {
  game.bind()
})

// 开局后自动切到分析页;结束后回到设置页
watch(() => game.gameStarted, (started) => {
  tab.value = started ? 'analysis' : 'settings'
})

const tabs: { key: Tab; label: string }[] = [
  { key: 'settings', label: zh.panel.settings },
  { key: 'analysis', label: zh.analysis.title },
  { key: 'history', label: zh.panel.history },
  { key: 'replay', label: zh.panel.replay },
  { key: 'llm', label: zh.panel.llmDebug },
]
</script>

<template>
  <div class="layout">
    <header>
      <h1>{{ zh.appTitle }}</h1>
      <div class="conn" :class="{ ok: game.connected }">
        {{ game.connected ? '已连接' : '未连接' }}
      </div>
      <button
        v-if="game.gameStarted"
        class="danger end-btn"
        @click="game.endGame()"
      >{{ zh.panel.endGame }}</button>
    </header>

    <main>
      <section class="stage">
        <TableView />
        <ActionBar />
        <div v-if="game.gameOverMessage" class="game-over panel">
          {{ game.gameOverMessage }}
        </div>
      </section>

      <aside>
        <nav class="tabs">
          <button
            v-for="t in tabs"
            :key="t.key"
            :class="{ active: tab === t.key }"
            @click="tab = t.key"
          >{{ t.label }}</button>
        </nav>
        <div class="tab-body">
          <SettingsPanel v-show="tab === 'settings'" />
          <AnalysisPanel v-show="tab === 'analysis'" />
          <HistoryPanel v-if="tab === 'history'" />
          <ReplayViewer v-if="tab === 'replay'" />
          <LlmDebugPanel v-if="tab === 'llm'" />
        </div>
      </aside>
    </main>

    <HandCompletedModal />
    <ToastHost />
  </div>
</template>

<style scoped>
.layout { display: flex; flex-direction: column; height: 100%; }
header {
  display: flex; align-items: center; gap: 14px;
  padding: 10px 18px; border-bottom: 1px solid var(--border);
  background: var(--bg-panel);
}
h1 { margin: 0; font-size: 1.05rem; color: var(--accent); }
.conn { font-size: .75rem; color: var(--red); }
.conn.ok { color: var(--green); }
.end-btn { margin-left: auto; }

main {
  flex: 1; display: grid; grid-template-columns: 1fr 380px;
  gap: 12px; padding: 12px; min-height: 0;
}
.stage { display: flex; flex-direction: column; gap: 10px; min-width: 0; }
.stage > :first-child { flex: 1; min-height: 0; }
.game-over { text-align: center; color: var(--accent); }

aside { display: flex; flex-direction: column; gap: 8px; min-height: 0; }
.tabs { display: flex; gap: 6px; flex-wrap: wrap; }
.tabs button { padding: 5px 10px; font-size: .8rem; }
.tabs button.active { border-color: var(--accent); color: var(--accent); }
.tab-body { flex: 1; min-height: 0; display: flex; flex-direction: column; }
.tab-body > * { flex: 1; min-height: 0; }

@media (max-width: 1000px) {
  main { grid-template-columns: 1fr; }
}
</style>
