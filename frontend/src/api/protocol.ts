/**
 * 服务器 ↔ 客户端通信契约的 TypeScript 类型。
 * 唯一权威定义见 docs/protocol.md（冻结版 v1）——改契约先改那里。
 */

export type Phase =
  | 'WAITING' | 'PRE_FLOP' | 'FLOP' | 'TURN' | 'RIVER' | 'SHOWDOWN' | 'FINISHED'

export type PlayerStatus = 'ACTIVE' | 'FOLDED' | 'ALL_IN' | 'OUT'

export type ActionName = 'fold' | 'check' | 'call' | 'bet' | 'raise'

export type BettingStructure = 'no_limit' | 'pot_limit' | 'fixed_limit'

export interface PlayerState {
  name: string
  chips: number
  seat: number
  status: PlayerStatus
  current_bet: number
  total_bet: number
  is_dealer: boolean
  is_small_blind: boolean
  is_big_blind: boolean
  is_human: boolean
  hands_won: number
  total_won: number
  rebuy_count: number
  hole_cards: string[]
}

export interface RankingEntry {
  rank: number
  desc: string
  prob: number
  samples?: number
}

export interface OddsEv {
  win_rate: number
  equity: number
  ci_95: number
  pot_odds_ratio: number
  required_equity: number
  ev: number
  ev_judgment: string
  to_call: number
  has_call_decision: boolean
}

export interface PotFinancials {
  pot_total: number
  dead_money: number
  sunk_cost: number
  to_call: number
}

export interface Analysis {
  hand_type_probs: Record<string, number>
  ranking_distribution: RankingEntry[]
  odds_ev: OddsEv
  pot_financials: PotFinancials
  sim_count: number
}

export interface GameUpdate {
  hand_id: number
  /** Number of actions already applied for this hand. */
  action_index: number
  phase: Phase
  community_cards: string[]
  pot_total: number
  current_bet: number
  dealer_index: number
  current_player_index: number
  betting_structure: string
  small_blind: number
  big_blind: number
  ante: number
  players: PlayerState[]
  winners: Record<string, number>
  legal_actions: string[]
  min_raise?: number
  max_bet?: number
  to_call?: number
  analysis?: Analysis
}

export interface ActionRequired {
  hand_id: number
  player: string
  timeout_seconds: number
  /** Unix timestamp in milliseconds from the server clock. */
  deadline_at: number
}

export interface ActionApplied {
  hand_id: number
  action_index: number
  player: string
  action: ActionName
  amount: number
  phase: Phase
  pot_total: number
  is_all_in: boolean
  occurred_at: number
}

export interface BotThinking {
  player: string
  is_llm: boolean
}

export interface ActionRejected {
  action: string
  reason: string
}

export interface LlmStatus {
  player: string
  status: 'ok' | 'fallback' | 'error'
  error_type?: 'auth' | 'rate_limit' | 'timeout' | 'parse' | 'network' | 'unknown'
  detail?: string
}

export interface HandCompletedPlayer {
  name: string
  is_folded: boolean
  is_winner: boolean
  net_profit: number
  best_five: string[]
  hand_description: string
  hole_cards: string[]
}

export interface HandCompleted {
  hand_id: number
  players: HandCompletedPlayer[]
  pot_total: number
  decision_review?: DecisionReview
}

export type DecisionVerdict = 'good_process' | 'review' | 'neutral'

export interface DecisionReview {
  action_index: number
  action: ActionName
  phase: Phase
  verdict: DecisionVerdict
  title: string
  detail: string
  equity?: number
  required_equity?: number
  ev?: number
}

export interface GameOver { message: string }
export interface GameError { message: string }

export interface BotConfig {
  style: string
  name?: string
  temperature?: number
  llm_config?: { provider?: string; model?: string }
}

export interface NewGamePayload {
  player_name: string
  bots: BotConfig[]
  starting_chips: number
  small_blind: number
  big_blind: number
  ante: number
  betting_structure: BettingStructure
}

export interface PlayerActionPayload {
  action: ActionName
  amount: number
}

/** Server → Client 事件表 */
export interface ServerToClientEvents {
  game_update: (s: GameUpdate) => void
  action_required: (p: ActionRequired) => void
  action_applied: (p: ActionApplied) => void
  bot_thinking: (p: BotThinking) => void
  action_rejected: (p: ActionRejected) => void
  llm_status: (p: LlmStatus) => void
  hand_completed: (p: HandCompleted) => void
  game_over: (p: GameOver) => void
  game_error: (p: GameError) => void
}

/** Client → Server 事件表 */
export interface ClientToServerEvents {
  new_game: (p: NewGamePayload) => void
  player_action: (p: PlayerActionPayload) => void
  continue_game: () => void
  end_game: () => void
}

/** REST: /api/bots/styles 条目 */
export interface BotStyleInfo {
  style: string
  display_name: string
  description: string
  temperature: number
}

/** REST: /api/game/replay */
export interface ReplayAction {
  player: string
  action: string
  amount: number
  is_all_in: boolean
}

export interface ReplaySnapshot {
  pot_total: number
  phase: string
  community_cards: string[]
  players: {
    name: string
    seat: number
    chips: number
    status: string
    current_bet: number
    total_bet: number
    rebuy_count: number
    is_dealer: boolean
    is_small_blind: boolean
    is_big_blind: boolean
    hole_cards: string[]
  }[]
}

export interface ReplayData {
  hand_id: number
  players: { name: string; hole_cards: string[]; is_human: boolean }[]
  community_cards: string[]
  actions: ReplayAction[]
  phase_boundaries: number[]
  winners: Record<string, number>
  winning_hands: Record<string, string>
  pot_total: number
  step_snapshots: ReplaySnapshot[]
  decision_review?: DecisionReview
}

export interface ReplaySummary {
  hand_id: number
  num_actions: number
  winners: Record<string, number>
  winning_hands: Record<string, string>
  pot_total: number
  community_cards: string[]
}

/** REST: /api/config/llm */
export interface LlmProviderConfig {
  provider: string
  model: string
  api_key: string
  base_url: string
  timeout_seconds: number
  temperature: number
  reasoning_effort: string
}

export interface LlmConfigPayload {
  primary: LlmProviderConfig
  enable_commentary: boolean
  enable_advisor: boolean
}
