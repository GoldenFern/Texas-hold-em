# Texas Hold'em Poker — LLM 驱动的德州扑克对战平台

全栈无限注德州扑克:自研引擎(严格规则校验+筹码守恒不变量)、Boltzmann-EV 决策机器人(统计物理模型,参数见 `docs/boltzmann_report.tex`)、LLM 对手(LangChain 多 Provider)、Flask-SocketIO 实时服务、Vue 3 + TypeScript 前端。

## 功能

- **完整扑克引擎** — 翻前→翻牌→转牌→河牌→摊牌;边池唯一权威算法(未匹配下注退款、弃牌死钱按层分配);NL / PL / FL 三种下注结构(FL 每街 1 bet + 3 raise 封顶);2–9 人桌;可设种子复现
- **Boltzmann-EV 机器人** — 六种温度风格(COLD 0.03 → CHAOS 1.20),P(a) ∝ exp(EV/T);按风格的对手响应参数表(`config/bot_profiles.json`)+ 基于观测 VPIP/AF 的逐对手收缩估计;翻前查 169×8 高精度多人胜率表(10 万次模拟/格)
- **LLM 机器人** — LangChain 统一接入 DeepSeek / Qwen / GLM / Kimi / MiniMax / 火山引擎 / LongCat / Anthropic / OpenAI / Ollama;结构化中文 CoT 决策;失败按类型上报(auth/rate_limit/timeout/parse/network)并由规则引擎兜底
- **实时 Web UI** — Vue 3 + Pinia + socket.io-client;CSS 椭圆牌桌、行动条、战局分析(equity±CI/EV/牌型分布)、逐步回放、LLM 调试面板、牌组皮肤
- **分析工具** — Treys 整数热路径蒙特卡洛(转牌圈河牌精确枚举)、按状态缓存、95% 置信区间

## 快速开始

```bash
# 1. Python 依赖
pip install -r requirements.txt

# 2. 前端构建(首次)
cd frontend && npm install && npm run build && cd ..

# 3. 生成翻前胜率表(仓库已带;重新生成约 3 分钟)
python scripts/build_preflop_table.py

# 4. 启动(默认 http://127.0.0.1:5000,仅本机)
python main.py
```

### LLM 对手(可选)

API Key 通过 `.env` 或环境变量提供,不写入任何 git 跟踪文件:

```bash
# .env(参考 .env.example)
THP_LLM_API_KEY=sk-...
# 或按 Provider: DEEPSEEK_API_KEY / DASHSCOPE_API_KEY / ANTHROPIC_API_KEY ...
```

其余 LLM 参数(Provider/模型/温度/思考模式)在网页设置面板或 `config/llm_config.json` 配置。

## 开发

```bash
python main.py                    # 后端(Flask-SocketIO, :5000)
cd frontend && npm run dev        # 前端热更新(Vite, :5173, 代理到 :5000)

python -m pytest tests/ -q        # 全部单测(不含真实 API)
python -m pytest tests/test_llm_live.py -q   # 真实 LLM API 冒烟(需 key)
python main.py --cli --hands 25   # CLI:6 个 Bot 自动对战
python scripts/sim_10000hands.py  # 万手模拟门禁(筹码守恒/零和)
```

通信契约(Socket.IO 事件 + REST)唯一权威:**`docs/protocol.md`**;前端类型 `frontend/src/api/protocol.ts` 据此手写。

## 目录结构

```
├── main.py                  # 入口(server / cli / test)
├── config/
│   ├── game_config.json     # 牌局参数
│   ├── bot_profiles.json    # Boltzmann 按风格参数表(τ/F_max/λ/ν/q_delta)
│   └── llm_config.json      # LLM Provider 配置(不含 Key)
├── src/
│   ├── engine/              # Card/Deck/HandEvaluator(Treys)/Player/Pot/GameState
│   ├── ai/                  # BoltzmannBot、OpponentModel、多人翻前表
│   ├── llm/                 # LangChain 客户端、Prompt、解析、上下文管理、LLMBot
│   ├── analysis/            # BattleAnalyzer(MC)、HandReporter(VPIP/PFR/AF)
│   ├── server/              # Flask 工厂、REST、SocketIO GameManager、会话注册表
│   └── utils/               # 常量、扑克数学、牌辅助/outs
├── frontend/                # Vue 3 + Vite + TS(构建到 static/dist)
├── docs/
│   ├── protocol.md          # 通信契约(冻结)
│   └── boltzmann_report.tex # 决策模型推导与数值实验
├── scripts/                 # 翻前表生成、万手/千手模拟门禁
└── tests/                   # 20 个测试文件(含筹码守恒性质测试)
```

## 机器人风格

温度 τ 是 softmax 探索系数(T = τ·pot),不是松紧度;各风格同时携带报告标定的对手响应参数:

| 风格 | τ | F_max | λ | ν | q_δ | 行为 |
|---|---|---|---|---|---|---|
| 极冷 COLD | 0.03 | 0.75 | 2.0 | 2.2 | 0.30 | 近乎确定性选最大 EV |
| 偏冷 COOL | 0.07 | 0.72 | 2.0 | 1.5 | 0.20 | 明显偏好高 EV |
| 均衡 BALANCED | 0.15 | 0.68 | 1.8 | 1.2 | 0.15 | 默认 |
| 偏热 WARM | 0.30 | 0.62 | 1.5 | 1.0 | 0.10 | EV 差异被部分抹平 |
| 炎热 HOT | 0.60 | 0.55 | 1.0 | 0.6 | 0.05 | 高度随机 |
| 混沌 CHAOS | 1.20 | 0.50 | 0.8 | 0.3 | 0.05 | 近乎均匀随机 |

千手模拟基准:弃牌率随 τ 单调(17%→30%),盈亏按纪律排序(COLD 最盈利、CHAOS 最亏),逐手零和精确为 0。

## LLM 决策链

```
GameState → PromptBuilder(注入牌力/赔率/outs/对手统计/会话上下文)
         → LangChain ChatModel(prompt | model)
         → ResponseParser(中英双语 JSON → 合法 Action,金额钳位)
         失败 → 规则引擎兜底 + llm_status 事件(带错误类型)上报前端
```

## 安全说明

- 默认仅绑定 `127.0.0.1`(局域网访问需显式 `--host 0.0.0.0`)
- SocketIO CORS 白名单(本机 :5000/:5173);`SECRET_KEY` 走 `THP_SECRET_KEY` 或随机
- `POST /api/config/llm` 的 `base_url` 仅接受官方预设或本机地址(防 SSRF)
- API Key 仅存 `.env`(已 gitignore),配置接口回显一律掩码
