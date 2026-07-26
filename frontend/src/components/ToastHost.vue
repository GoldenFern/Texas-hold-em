<script setup lang="ts">
import { useToastStore } from '@/stores/toast'

const store = useToastStore()
</script>

<template>
  <Teleport to="body">
    <div class="toast-host">
      <TransitionGroup name="toast">
        <div
          v-for="t in store.toasts"
          :key="t.id"
          class="toast"
          :class="t.kind"
          @click="store.dismiss(t.id)"
        >
          {{ t.text }}
        </div>
      </TransitionGroup>
    </div>
  </Teleport>
</template>

<style scoped>
.toast-host {
  position: fixed; top: 14px; right: 14px; z-index: 100;
  display: flex; flex-direction: column; gap: 8px; max-width: 340px;
}
.toast {
  padding: 10px 14px; border-radius: 8px; cursor: pointer;
  background: var(--bg-panel-2); border: 1px solid var(--border);
  font-size: .85rem; box-shadow: 0 4px 16px rgba(0,0,0,.4);
}
.toast.warn { border-color: var(--accent); }
.toast.error { border-color: var(--red); background: #332020; }
.toast-enter-active, .toast-leave-active { transition: all .25s; }
.toast-enter-from, .toast-leave-to { opacity: 0; transform: translateX(24px); }
</style>
