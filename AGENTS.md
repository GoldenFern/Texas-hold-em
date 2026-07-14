---
description: 
alwaysApply: true
---

# CLAUDE.md — Texas Hold'em Poker

## 项目概述

全栈德州扑克 No-Limit 应用：完整游戏引擎 + 规则 AI Bot + **LLM 驱动 AI 对手**（Claude / GPT / Ollama）+ Flask-SocketIO 实时 Web 界面 + 蒙特卡洛分析工具。

## 启动命令

```bash
python main.py                    # Web 服务器（默认 http://localhost:5000）
python main.py --cli --hands 25   # CLI 模式（6 个 AI Bot 自动对战）
python main.py --test             # 运行全部测试
pytest tests/ -v                  # 单测详细输出
```

## 架构分层

| 层 | 目录 | 职责 |
|---|---|---|
| 游戏引擎 | `src/engine/` | Card / Deck / Hand evaluator / Player / Pot / GameState 状态机 |
| AI 机器人 | `src/ai/` | 6 种 Bot 风格（TAG/LAG/NIT/CallingStation/Maniac/Shark）+ 策略计算 |
| LLM 集成 | `src/llm/` | 多 Provider 客户端、Prompt 构建、响应解析、降级链、LLMBot |
| 分析工具 | `src/analysis/` | 蒙特卡洛胜率、底池赔率/隐含赔率、EV 计算、牌局记录 |
| Web 服务 | `src/server/` | Flask 工厂 + REST API + SocketIO 实时事件 + GameManager |
| 前端 | `static/` `templates/` | 桌面风格扑克桌 UI（Canvas 椭圆布局）、操作面板、分析面板 |

## 关键设计

### GameState 事件机制
`GameState` 使用事件回调（`on("hand_finished", ...)`）与上层解耦。Web 层通过回调推送 SocketIO 消息，而非引擎层主动调用 Web API。

### 牌型评估（Hand Evaluator）
`HandEvaluator.evaluate(cards)` 接收 5-7 张牌，生成 C(7,5)=21 种组合，返回最优 `HandResult`。评分系统使用 `(牌型等级, 踢脚1, 踢脚2, ...)` 元组，可直接用 Python 元组比较。正确处理 A-2-3-4-5 轮子顺子。

### LLM Bot 决策链
```
GameState → PromptBuilder（注入手牌强度/赔率/胜率）→ LLM Client
→ ResponseParser（提取 JSON、映射动作、裁剪数额）
→ 失败时 FallbackChain：主 LLM → 备选 LLM → 规则引擎
```

`call_frequency` 控制 LLM 调用频率：`every`（每次）、`critical`（关键决策）、`mixed`（周期性 + 关键）。

### Bot 决策验证
所有 Bot 动作在 `game.apply_action()` 前必须通过 `game.get_legal_actions()` 校验。非法动作默认降级为 Check > Call > Fold。

### 边池计算
支持最多 9 名玩家不同 all-in 数额的边池分配，使用从低到高排序的 all-in 额进行多轮分配。

## 编程约定

- Python 3.13+，类型标注使用 `from __future__ import annotations`
- 编码：所有文件读写显式 UTF-8
- 配置：通过 `config/*.json` 管理，不硬编码
- LLM API Key：通过环境变量或 `.env` 文件加载（`THP_LLM_*` 前缀优先）

## LLM 依赖（可选）

核心游戏无需 LLM。启用 LLM Bot 时按需安装：

```bash
pip install anthropic>=0.30.0    # Claude
pip install openai>=1.0.0        # GPT
pip install requests>=2.31.0     # Ollama 本地
pip install python-dotenv        # .env 加载
```

环境变量：`ANTHROPIC_API_KEY` / `OPENAI_API_KEY` / `THP_LLM_*`（项目专用前缀）。

## Agent skills

### Issue tracker

GitHub Issues（`gh` CLI）；外部 PR 不作为 triage 入口。详见 `docs/agents/issue-tracker.md`。

### Triage labels

五个标准 triage 标签，名称与默认一致。详见 `docs/agents/triage-labels.md`。

### Domain docs

单上下文布局：根目录 `CONTEXT.md` + `docs/adr/`。详见 `docs/agents/domain.md`。

## Cursor Cloud specific instructions

- 纯 Python 单进程应用，无数据库/Redis 等外部服务；依赖通过 `pip install -r requirements.txt` 安装（启动脚本已自动执行）。
- 运行时统一用 `python3`（VM 无 `python` 别名）：`python3 main.py`（Web，`0.0.0.0:5000`）、`python3 main.py --cli --hands N`、`python3 -m pytest tests/ -v`。
- 虽然 `环境.yml`/文档写的是 Python 3.13+，但 VM 自带 3.12.3 即可正常运行（代码用 `from __future__ import annotations`，全部测试通过）。
- 无 lint/format/type-check 工具配置（无 ruff/flake8/black/mypy），仅有 `pytest`。
- 测试中 `tests/test_llm_live.py` 的 5 个用例在未设置 `DEEPSEEK_API_KEY`/`THP_LLM_*` 等真实 API Key 时会自动 skip，属正常现象；核心游戏与规则 Bot 无需任何 LLM Key。
- `pip` 会把 `pytest` 等脚本装到未加入 PATH 的 `~/.local/bin`；请用 `python3 -m pytest` 而非直接 `pytest`。
