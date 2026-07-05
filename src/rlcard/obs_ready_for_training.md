# obs_ready_for_training — Progressive Observation 审计清单

RLCard observation 编码的完整性审计，在离线训练前必须逐项关闭。

## 当前状态：Phase A（54 维向量）

| # | 维度 | 范围 | 状态 | 说明 |
|---|------|------|------|------|
| 1 | 卡牌 one-hot | [0:52) | 已实现 | 底牌 + 公共牌可见位置置 1；编码与 RLCard 标准一致 |
| 2 | my_chips / BB | [52] | 已实现 | BB 归一化筹码编码 |
| 3 | opponent_chips / BB | [53] | 已实现 | 单挑对手筹码（多人桌取第一个未弃牌对手） |

## 训练前需关闭的渐进式 Gaps

### Gap 1: 卡牌编码完整性（card encoding）
- [ ] **社区牌位置语义**：当前仅 one-hot 所有可见牌，未区分底牌 vs 公共牌。训练时需为底牌和每张公共牌（flop/turn/river）分配独立编码槽，或使用 RLCard 标准 6-card 编码格式
- [ ] **手牌组合特征**：同花/连张等组合信息未显式编码，当前依赖 agent 从 one-hot 中隐式学习
- **参考**: `MirrorAdapter.encode_observation()` / `card_to_rlcard_index()`

### Gap 2: 筹码编码槽位（BB slots）
- [ ] **历史下注轮编码**：当前无 street-level 下注历史。RLCard 标准 env 在 observation 中编码各轮下注额。需为 pre-flop/flop/turn/river 各添加 `my_bet/BB` 与 `opponent_bet/BB` 槽位
- [ ] **有效深度归一化**：当前仅编码绝对筹码/BB，未编码有效深度（min(my_chips, opp_chips)/BB），而有效深度是策略的关键决定因素
- **参考**: `MirrorAdapter.encode_observation()` 第 95-103 行

### Gap 3: 动作合法性对称性（legal_actions symmetry）
- [ ] **对称 legal_actions 编码**：当前 `get_legal_rlcard_actions()` 仅返回合法 action_id 列表。训练时需确认 RLCard env 的 `legal_actions` 向量格式（one-hot 或 index list）与当前适配层一致
- [ ] **动作掩码验证**：需验证 agent 在训练中不会因 legal_actions 编码格式不匹配而选择非法动作
- **参考**: `MirrorAdapter.get_legal_rlcard_actions()` / `RLCardBot.decide()` 第 120-130 行

### Gap 4: 多人桌扩展（multi-player extension）
- [ ] **对手编码扩展**：当前 observation 仅编码单挑对手（53 维），多人桌需为每个对手编码独立槽位
- [ ] **位置编码**：按钮/盲注位置信息未编码，对策略有影响
- **参考**: `MirrorAdapter._find_opponent()` — 当前仅返回第一个未弃牌对手

### Gap 5: 动作空间版本锁定
- [ ] **动作空间版本**：当前使用 5-action 抽象（FOLD/CHECK_CALL/RAISE_HALF_POT/RAISE_POT/ALL_IN）。训练前需确认目标 RLCard env 的动作空间与此一致
- [ ] **加注额量化**：如训练使用更细粒度的加注额（如 1/4 pot, 3/4 pot），需扩展适配层

## 审计签名

| 日期 | 审计人 | 变更 |
|------|--------|------|
| 2026-07-05 | initial | Phase A 基线；5 项 gaps 待关闭 |
