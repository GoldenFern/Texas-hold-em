---
description: 
alwaysApply: true
---

# CLAUDE.md — Texas Hold'em Poker

## 项目概述

全栈德州扑克 No-Limit 应用:自研引擎 + Boltzmann-EV Bot + **LLM 驱动 AI 对手**(LangChain 多 Provider)+ Flask-SocketIO 服务 + Vue 3 + TS 前端 + 蒙特卡洛分析。

## 启动命令

```bash
python main.py                    # Web 服务器(默认 http://127.0.0.1:5000)
cd frontend && npm run dev        # 前端开发热更新(:5173 代理到 :5000)
cd frontend && npm run build      # 前端构建到 static/dist(生产)
python main.py --cli --hands 25   # CLI 模式(6 个 AI Bot 自动对战)
python -m pytest tests/ -q --ignore=tests/test_llm_live.py   # 全部单测
python scripts/sim_10000hands.py  # 万手守恒/零和门禁(失败退出码 1;--hands N 可减量)
python scripts/build_preflop_table.py   # 重新生成翻前多人胜率表
python scripts/ev_raise_scenarios.py    # 典型场景 EV-加注曲线批量分析(图输出 tmp/ev_raise_curves/)
```

## 架构分层

| 层 | 目录 | 职责 |
|---|---|---|
| 游戏引擎 | `src/engine/` | Card / Deck(可设种) / HandEvaluator(Treys) / Player / **Pot(边池唯一权威)** / GameState 状态机 |
| AI 机器人 | `src/ai/` | BoltzmannBot(6 温度风格)+ OpponentModel(逐对手收缩估计)+ 169×8 多人翻前表 |
| LLM 集成 | `src/llm/` | LangChain 客户端(类型化错误)、PromptBuilder、ResponseParser、ContextManager、LLMBot |
| 分析工具 | `src/analysis/` | BattleAnalyzer(Treys 整数 MC + 状态缓存 + CI)、HandReporter(VPIP/PFR/AF) |
| Web 服务 | `src/server/` | Flask 工厂 + REST + SocketIO GameManager + GameSessionRegistry |
| 前端 | `frontend/` | Vue 3 + Vite + TS + Pinia;构建产物在 `static/dist` |

## 关键设计

### 通信契约
`docs/protocol.md` 是 Socket.IO/REST 的**唯一权威**;改契约先改它,前端类型在 `frontend/src/api/protocol.ts` 同步。

### 引擎不变量(改动引擎必看)
- `players` 列表索引 == seat(构造时断言)
- 边池仅由 `Pot.collect_bets()` 计算:先退未匹配溢出(死钱算匹配额),再按未弃牌档位分层;层不可无主(RuntimeError),分层总额必等于投入
- 免费弃牌非法(to_call=0 时无 FOLD)——防无人认领死钱
- OUT(零筹码未重购)玩家在所有流程判定中等价弃牌
- min_raise 每街重置;FL 每街 1 bet + 3 raise 封顶
- 回归安全网:`tests/test_chip_conservation.py`(固定种子逐手断言守恒)+ `scripts/sim_10000hands.py`

### Bot 决策契约(RLCard 集成依赖,见 issues #8–12)
所有 Bot 实现 `decide(game_state, player) -> Action`,**签名不可改**。附加依赖经构造器/setter 注入:
- `bot.set_opponent_model(OpponentModel)` —— GameManager.create_game 注入共享实例(reporter 统计 → 逐对手 F_max/λ 收缩混合,无数据退回 `config/bot_profiles.json` 的风格常数)
- 引擎动作面仅 FOLD/CHECK/CALL/BET/RAISE;全下 = BET/RAISE 到 max_bet
- 新增 Bot 类型(如 RLCard):在 `BotFactory` 注册风格,`GameManager.create_game` 分支创建;非法动作会被 `game_error` 上报后降级,合法性以 `get_legal_actions` 为准

### GameManager 并发模型
- SocketIO 显式 `async_mode="threading"`(eventlet 已弃用并从依赖移除;未 monkey_patch 时 green thread + 原生锁会冻结事件循环),bot 循环跑在后台线程,原生 `threading.Lock/Event` 语义正确
- Event 等待用 `_wait_event`(socketio.sleep 0.1s 轮询,禁用阻塞式 wait);人类行动超时以 `time.monotonic()` 截止时间为准,禁止按循环次数累计(防调度/GC 漂移)
- LLM 决策在锁外执行,回锁后按 generation/hand_id/player 三重校验;人类等待侧超时自动行动同样带 generation 快照守卫(`_auto_act_for_human(gen)`)
- `create_game` 三段式:参数校验(含数值类型/风格/重名/auto_rebuy 布尔)→ 终止旧循环递增代际 → 构建失败回滚到无游戏一致状态并上报 `game_error`;新局清空 reporter(战绩/对手模型从零开始)
- 重购策略由 `new_game.auto_rebuy` 决定:默认 `true` 现金局,破产玩家下一手按 `starting_chips` 重购;`false` 锦标赛,破产出局,剩 1 人有筹码时先广播末手 `hand_completed`,用户继续后再 `game_over`
- 所有 SocketIO 入口对客户端数据做严格校验(金额仅接受有限数字,拒绝 bool/NaN/字符串),`call/check/fold` 的 amount 一律归一为 0,任何入口异常必须回报 `action_rejected`/`game_error`,严禁静默吞
- `_broadcast_state` 锁内只做快照;MC 分析在后台任务用数值快照计算(`BattleAnalyzer.analyze_snapshot`)
- 循环级异常 → `game_error` 事件 + 循环存活,严禁静默吞
- 浏览器 Origin 白名单默认 5000/5173;自定义端口自动补本机地址,局域网/域名经 `--allow-origin` 或 `create_app(extra_origins=...)` 追加

### LLM 层
- max_tokens 默认 4096(勿改回大值:超过 Provider 上限会导致全部调用 400 并静默降级)
- API Key 只进 `.env`(`THP_LLM_API_KEY` 或按 Provider 环境变量),严禁写入 git 跟踪文件
- 失败分类:auth / rate_limit / timeout / parse / network → `llm_status` 事件

### 前端交互与布局
- `action_applied` 以 `(hand_id, action_index)` 去重；同动作的分析广播不会重复生成行动流。
- 截止时间使用 `action_required.deadline_at`；人类行动时保存当时可见的决策数据，结束后从结算弹窗进入复盘。
- 桌面手牌和公共牌为 72×102px，移动端自己的手牌为 52×74px；牌面点数和花色由原生文本增强，素材来源不变。
- 650px 以下多人桌采用左右分列座位和 3+2 公共牌；行动流在牌桌下方。小屏结算弹窗和回放可换行，避免横向裁切。
- 设置页可选重购规则（现金局/锦标赛，默认现金局，存 localStorage）；Vite `base` 仅 build 指向 `/static/dist/`，dev 用 `/`（否则 `/static` 代理会吞掉源码模块导致 404）。
- 前端检查：`cd frontend && npm run test && npm run typecheck && npm run build`。测试命令使用 Node.js 22.6+ 的原生 TypeScript 类型剥离，不增加测试库依赖。

## 编程约定

- Python 3.13+,类型标注 + `from __future__ import annotations`;Google 风格 Docstring;中文注释
- 编码:所有文件读写显式 UTF-8
- 配置进 `config/*.json`;魔法数字须有出处(报告/基准)
- Conventional Commits(英文)
- 前端:禁 `v-html`(XSS);文案集中 `frontend/src/i18n/zh.ts`

## RLCard 依赖（可选）

核心游戏无需 RLCard。启用 RLCard Bot 时按需安装：

```bash
pip install rlcard              # Phase A：RandomAgent（无需训练）
pip install rlcard[torch]       # Phase B：DQN / DMC 训练与推理
# 或：pip install -r requirements-rlcard.txt
```

模型工件放置在 `models/rlcard/`（`*.pth` / `*.tar` 已 gitignore）。
环境变量：`THP_RLCARD_MODEL_PATH` 可覆盖默认模型路径。

### 离线训练（Phase B）

```bash
# DQN（默认，较快产出 .pth）
python scripts/train_rlcard.py --algorithm dqn --num-episodes 500

# DMC（较慢，产出 .tar）
python scripts/train_rlcard.py --algorithm dmc --total-frames 50000
```

训练在 RLCard `no-limit-holdem` 沙箱内自博弈，不使用镜像适配器；超参数与有效深度见 `config/rlcard_config.json`。

### 对局中使用训练模型

1. 将 `config/rlcard_config.json` 中 `agent_type` 设为 `"dqn"` 或 `"dmc"`，`model_path` 指向工件路径
2. 或设置环境变量：`THP_RLCARD_MODEL_PATH=models/rlcard/nlh_dqn.pth`
3. Web/CLI 创建 **单挑** RLCard Bot（1 人类 + 1 RLCard Bot）

`bot_configs[].rlcard_config` 可 per-bot 覆盖上述字段。

## Agent skills

### Issue tracker
GitHub Issues(`gh` CLI);外部 PR 不作为 triage 入口。详见 `docs/agents/issue-tracker.md`。

### Triage labels
五个标准 triage 标签,名称与默认一致。详见 `docs/agents/triage-labels.md`。

### Domain docs
多上下文布局：根目录 `CONTEXT-MAP.md` 指向 `CONTEXT.md` + `src/rlcard/CONTEXT.md`。详见 `docs/agents/domain.md`。
