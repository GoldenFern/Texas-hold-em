<script setup lang="ts">
import { computed } from 'vue'
import { useSettingsStore } from '@/stores/settings'
import { cardImagePath, cardBackPath, isRedSuit } from '@/utils/deckSkin'

const props = withDefaults(defineProps<{
  card: string          // 牌串如 "A♠";"??" 表示暗牌;"" 表示空位
  small?: boolean
  dimmed?: boolean
}>(), { small: false, dimmed: false })

const settings = useSettingsStore()

const isHidden = computed(() => props.card === '??')
const imgSrc = computed(() =>
  isHidden.value ? cardBackPath(settings.deckSkin) : cardImagePath(props.card, settings.deckSkin))
const red = computed(() => !isHidden.value && isRedSuit(props.card))
</script>

<template>
  <div class="card" :class="{ small, dimmed, empty: !card }">
    <img v-if="card && imgSrc" :src="imgSrc" :alt="isHidden ? '牌背' : card" draggable="false" />
    <span v-else-if="card" class="text-face" :class="{ red }">{{ card }}</span>
  </div>
</template>

<style scoped>
.card {
  width: 52px;
  height: 74px;
  border-radius: 6px;
  background: #0e1319;
  border: 1px solid #2a3441;
  display: flex;
  align-items: center;
  justify-content: center;
  overflow: hidden;
  flex-shrink: 0;
}
.card.small { width: 38px; height: 54px; }
.card.dimmed { opacity: .45; filter: grayscale(.6); }
.card.empty { background: transparent; border-style: dashed; opacity: .25; }
.card img { width: 100%; height: 100%; object-fit: cover; user-select: none; }
.text-face { font-weight: 700; font-size: .95rem; color: #1c2733; background: #f4f6f8; width: 100%; height: 100%; display: flex; align-items: center; justify-content: center; }
.text-face.red { color: #c33; }
</style>
