/** REST API 封装。 */

import type {
  BotStyleInfo, LlmConfigPayload, ReplayData, ReplaySummary,
} from './protocol'

async function getJson<T>(url: string): Promise<T> {
  const resp = await fetch(url)
  if (!resp.ok) throw new Error(`${url} -> HTTP ${resp.status}`)
  return resp.json() as Promise<T>
}

export function fetchBotStyles(): Promise<BotStyleInfo[]> {
  return getJson('/api/bots/styles')
}

export function fetchReplayList(): Promise<ReplaySummary[]> {
  return getJson('/api/game/replays')
}

export function fetchReplay(handId?: number): Promise<ReplayData> {
  const q = handId != null ? `?hand_id=${handId}` : ''
  return getJson(`/api/game/replay${q}`)
}

export function fetchLlmContext(): Promise<Record<string, unknown>> {
  return getJson('/api/game/llm_context')
}

export function fetchLlmConfig(): Promise<LlmConfigPayload> {
  return getJson('/api/config/llm')
}

export async function saveLlmConfig(payload: LlmConfigPayload): Promise<void> {
  const resp = await fetch('/api/config/llm', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  })
  const data = await resp.json().catch(() => ({}))
  if (!resp.ok) {
    throw new Error((data as { message?: string }).message ?? `HTTP ${resp.status}`)
  }
}

export function fetchStatsSummary(): Promise<{
  total_hands: number
  player_stats: {
    name: string; hands_played: number; hands_won: number
    vpip: number; pfr: number; aggression_factor: number
    win_rate: number; profit: number
  }[]
}> {
  return getJson('/api/game/analysis')
}
