# 服务器 ↔ 客户端通信契约（冻结版 v1）

本文件是 Socket.IO 事件与 REST API 的唯一权威定义。前端 TypeScript 类型
(`frontend/src/api/protocol.ts`)据此手写。修改契约必须先改本文件再动代码。

## Socket.IO 事件

### Client → Server

| 事件 | 载荷 | 说明 |
|---|---|---|
| `new_game` | `{player_name, bots: [{style, name?, temperature?, llm_config?: {provider?, model?}}], starting_chips, small_blind, big_blind, ante, betting_structure: "no_limit"\|"pot_limit"\|"fixed_limit"}` | 创建新游戏(替换当前游戏) |
| `player_action` | `{action: "fold"\|"check"\|"call"\|"bet"\|"raise", amount: number}` | 人类玩家动作;amount 仅 bet/raise 有意义(本轮下注总额) |
| `continue_game` | — | 手牌结束后继续下一手 |
| `end_game` | — | 结束当前游戏 |

### Server → Client

| 事件 | 载荷 | 说明 |
|---|---|---|
| `game_update` | 见下方 GameUpdate | 每次状态变化后广播 |
| `action_required` | `{player: string, timeout_seconds: number}` | 轮到人类玩家行动;超时后服务器自动过牌/弃牌 |
| `bot_thinking` | `{player: string, is_llm: boolean}` | Bot 开始思考(LLM 决策可能耗时较长) |
| `action_rejected` | `{action: string, reason: string}` | 玩家动作被拒(非法/不是回合/无效风格) |
| `llm_status` | `{player: string, status: "ok"\|"fallback"\|"error", error_type?: "auth"\|"rate_limit"\|"timeout"\|"parse"\|"network", detail?: string}` | LLM 调用结果上报 |
| `hand_completed` | `{hand_id, players: [{name, is_folded, is_winner, net_profit, best_five: string[], hand_description, hole_cards: string[]}], pot_total}` | 一手结束,等待 continue_game/end_game |
| `game_over` | `{message: string}` | 游戏结束(人数不足或用户主动结束) |
| `game_error` | `{message: string}` | 服务器内部错误(bot 循环异常等),游戏可能需要重建 |

### GameUpdate 结构

```
{
  hand_id: number,
  phase: "WAITING"|"PRE_FLOP"|"FLOP"|"TURN"|"RIVER"|"SHOWDOWN"|"FINISHED",
  community_cards: string[],        // 如 ["A♠","T♥"]
  pot_total: number,
  current_bet: number,
  dealer_index: number,
  current_player_index: number,
  betting_structure: string,
  small_blind: number, big_blind: number, ante: number,
  players: [{
    name, chips, seat, status: "ACTIVE"|"FOLDED"|"ALL_IN"|"OUT",
    current_bet, total_bet, is_dealer, is_small_blind, is_big_blind,
    is_human, hands_won, total_won, rebuy_count,
    hole_cards: string[]            // 不可见时为 ["??","??"],出局/弃牌为 []
  }],
  winners: {[name]: number},
  legal_actions: string[],          // 仅轮到人类时非空
  min_raise?: number, max_bet?: number, to_call?: number,
  analysis?: {                      // 人类底牌可见时才有
    hand_type_probs: {[牌型显示名]: number},
    ranking_distribution: [{rank, desc, prob, samples?}],   // rank=-1 条目为 equity
    odds_ev: {win_rate, equity, ci_95, pot_odds_ratio, required_equity,
              ev, ev_judgment, to_call, has_call_decision},
    pot_financials: {pot_total, dead_money, sunk_cost, to_call},
    sim_count: number
  }
}
```

注: `analysis` 仅以子对象形式提供（迁移期的顶层平铺已随 Vue 前端上线移除）。

## REST API

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/` | 前端入口(构建产物) |
| GET | `/api/game/state` | 当前游戏状态(GameUpdate 的无 analysis 版本) |
| GET | `/api/game/history` | 最近 20 手摘要 |
| GET | `/api/game/analysis` | reporter 全局统计(VPIP/PFR/AF/盈亏) |
| GET | `/api/game/replay?hand_id=` | 单手完整回放(actions/phase_boundaries/step_snapshots) |
| GET | `/api/game/replays` | 可回放手牌摘要(最近 50) |
| GET | `/api/game/bots` | Bot 名称与类型(不含内部统计) |
| GET | `/api/game/llm_context` | 最近一次 LLM 调用上下文(调试面板) |
| GET | `/api/config/llm` | LLM 配置(api_key 掩码为 "***") |
| POST | `/api/config/llm` | 保存 LLM 配置;`api_key:"***"`=保留,`""`=清除;base_url 仅接受预设或本地地址 |
| GET | `/api/bots/styles` | 可选 Bot 风格列表 |

已删除(与 SocketIO 重复,前端未使用):`POST /api/game/new`、`POST /api/game/action`。

## 会话模型

当前为单会话:`GameSessionRegistry` 持 `{"default": GameManager}`。
未来多桌扩展:注册表加键、`GameManager._emit()` 加 `room=` 参数,契约不变。
