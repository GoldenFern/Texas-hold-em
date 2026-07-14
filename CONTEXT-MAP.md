# Context Map

## Contexts

- [前端展示域](./CONTEXT.md) — 牌组皮肤、本地偏好与 UI 展示概念
- [游戏 AI 域](./src/rlcard/CONTEXT.md) — 机器人对手、RL 集成与镜像适配概念（RLCard 集成）

## Relationships

- **游戏 AI 域 → 游戏引擎**：`RLCard Bot` 通过镜像适配器读取 `GameState`、输出 `Action`；不驱动状态机
- **游戏 AI 域 → 前端展示域**：无直接耦合；Bot 风格选择在 Web UI 独立配置
