<script setup lang="ts">
import { ref } from 'vue'
import { fetchLlmContext } from '@/api/rest'
import { zh } from '@/i18n/zh'

interface LlmCtx {
  status?: string
  provider?: string
  model?: string
  system_prompt?: string
  user_prompt?: string
  raw_response?: string
  error?: string
  latency_seconds?: number
  call_index?: number
}

const ctx = ref<LlmCtx | null>(null)
const loading = ref(false)

async function refresh() {
  loading.value = true
  try {
    const data = await fetchLlmContext() as LlmCtx
    ctx.value = data.status === 'ok' ? data : null
  } catch {
    ctx.value = null
  } finally {
    loading.value = false
  }
}

refresh()
</script>

<template>
  <div class="panel debug scroll">
    <h3>
      {{ zh.panel.llmDebug }}
      <button class="mini" :disabled="loading" @click="refresh">{{ zh.llmDebug.refresh }}</button>
    </h3>
    <template v-if="ctx">
      <div class="meta">
        {{ ctx.provider }}/{{ ctx.model }}
        · {{ zh.llmDebug.latency }} {{ ctx.latency_seconds }}s
        <template v-if="ctx.call_index">· {{ zh.llmDebug.callIndex }} {{ ctx.call_index }}</template>
      </div>
      <div v-if="ctx.error" class="error">{{ zh.llmDebug.error }}: {{ ctx.error }}</div>
      <details>
        <summary>{{ zh.llmDebug.systemPrompt }}</summary>
        <pre>{{ ctx.system_prompt }}</pre>
      </details>
      <details open>
        <summary>{{ zh.llmDebug.userPrompt }}</summary>
        <pre>{{ ctx.user_prompt }}</pre>
      </details>
      <details open>
        <summary>{{ zh.llmDebug.response }}</summary>
        <pre>{{ ctx.raw_response }}</pre>
      </details>
    </template>
    <div v-else class="empty">{{ zh.llmDebug.empty }}</div>
  </div>
</template>

<style scoped>
.debug { font-size: .8rem; }
.mini { padding: 2px 8px; font-size: .75rem; margin-left: 8px; }
.meta { color: var(--text-dim); margin-bottom: 6px; }
.error { color: var(--red); margin-bottom: 6px; }
pre {
  white-space: pre-wrap; word-break: break-word;
  background: #10151c; padding: 8px; border-radius: 6px;
  max-height: 260px; overflow-y: auto; font-size: .74rem;
}
summary { cursor: pointer; color: var(--accent-2); margin: 6px 0; }
.empty { color: var(--text-dim); }
</style>
