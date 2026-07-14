# 游戏 AI 域 — RL 集成

全栈德州扑克应用中，与机器人对手及 RLCard 强化学习集成相关的领域概念。

## Language

**镜像适配器（Mirror Adapter）**:
每次决策时将 `GameState` 单向翻译为 RLCard observation，调用 agent 后将动作映射回引擎 `Action`；不维护第二份游戏状态。
_Avoid_: 双引擎、状态同步

**RLCard Bot**:
实现 `BotBase` 的机器人子类，内部持有 RLCard agent，通过镜像适配器决策。
_Avoid_: RL 机器人（与 LLM Bot 混淆）

**单挑 RL 对手（Heads-Up RL Opponent）**:
仅在 2 人桌（1 人类 + 1 Bot）激活的 RLCard 驱动对手；obs 与 RLCard 标准编码对齐。
_Avoid_: 多人 RL 对手（Phase A 不支持）

**动作抽象（Action Abstraction）**:
RLCard NLHE 将加注归纳为半池、满池、全下等离散动作 id；适配层映射为引擎的 `BET`/`RAISE` 金额。
_Avoid_: 原始加注（RLCard 不暴露连续金额）

**底池加注额（Pot-Sized Raise Total）**:
玩家本轮下注的目标总投入（含跟注部分）；满池加注 = `to_call + pot.total`（`pot.total` 为行动前底池）。
_Avoid_: 加注增量（易与最小加注混淆）

**RL 集成层（RL Integration Layer）**:
封装 RLCard 依赖的模块边界，负责镜像适配与可选能力探测；不包含游戏引擎逻辑。
_Avoid_: AI 模块（与规则 Bot 混称）

**可选能力（Optional Capability）**:
未安装 `rlcard` 时，核心游戏与 Web 服务正常运行；UI 不展示 RLCard Bot 选项。
_Avoid_: 必选依赖

**渐进式 obs（Progressive Observation）**:
Phase A 实现牌面 + BB 归一化筹码编码及完整 `legal_actions` 映射；非关键维度可暂填零，训练前需完整性审计。
_Avoid_: 完整状态（Phase A 不要求一次到位）

**策略工件（Policy Artifact）**:
离线训练产出的模型权重文件（如 `.pth`），仅用于推理，不含游戏逻辑。
_Avoid_: 模型文件（过于泛化）

**离线训练（Offline Training）**:
在 RLCard `no-limit-holdem` 环境内自博弈训练；不经过镜像适配器。
_Avoid_: 在线学习

**有效深度（Effective Stack Depth）**:
起始筹码 ÷ 大盲注；衡量单挑策略行为的关键参数。
_Avoid_: 筹码量（未归一化）

**BB 归一化（BB-Normalized Encoding）**:
筹码与下注额以大盲为单位写入 observation（如 `obs[52] = my_chips / bb`），消除绝对面值差异。
_Avoid_: 绝对筹码编码
