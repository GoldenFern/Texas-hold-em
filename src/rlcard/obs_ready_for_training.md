# obs_ready_for_training — Progressive Observation 审计清单

RLCard observation 编码的完整性审计，在离线训练前必须逐项关闭。

## 当前状态：Phase B 基线（54 维向量，与 RLCard env 对齐）

| # | 维度 | 范围 | 状态 | 说明 |
|---|------|------|------|------|
| 1 | 卡牌 one-hot | [0:52) | **已关闭** | 底牌 + 公共牌；`state_encoder.card_to_rlcard_index` 与 RLCard `card2index` 一致 |
| 2 | my_chips / BB | [52] | **已关闭** | BB 归一化；与 RLCard `obs[52]` 语义一致 |
| 3 | max_chips / BB | [53] | **已关闭（Phase B）** | 由「对手筹码」改为 `max(active_chips)/BB`，与 RLCard `_extract_state` 对齐，消除 train/serve 漂移 |

**共享模块**：`src/rlcard/state_encoder.py` — 镜像适配器与 `scripts/train_rlcard.py` 均导入。

## 训练前需关闭的渐进式 Gaps

### Gap 1: 卡牌编码完整性（card encoding）
- [x] **社区牌位置语义**：Phase B 沿用 RLCard 标准 54 维 one-hot（不区分 flop/turn/river 槽位）；与训练 env 一致，**显式接受**为 Phase B 范围
- [ ] **手牌组合特征**：同花/连张等组合信息未显式编码 — **推迟**至 Phase C（非 Phase B 阻断项）
- **参考**: `state_encoder.encode_from_game_state()` / `card_to_rlcard_index()`

### Gap 2: 筹码编码槽位（BB slots）
- [ ] **历史下注轮编码**：各 street 下注额未编码 — **推迟**（RLCard NLHE env 同样未提供）
- [ ] **有效深度归一化**：未单独编码 `min(my, opp)/BB` — **推迟**；`max(all_chips)` 已提供深度代理信号
- **参考**: `state_encoder.encode_from_game_state()`

### Gap 3: 动作合法性对称性（legal_actions symmetry）
- [x] **对称 legal_actions 编码**：`policy_loader.build_agent_state()` 按 agent 类型分发 list（DQN）或 OrderedDict（DMC）
- [x] **动作掩码验证**：`RLCardBot.decide()` 对非法动作降级；`test_rlcard_bot` / `test_rlcard_policy` 覆盖
- **参考**: `MirrorAdapter.get_legal_rlcard_actions()` / `RLCardBot.decide()`

### Gap 4: 多人桌扩展（multi-player extension）
- [ ] **对手编码扩展**：仅单挑 — **显式超出 Phase B 范围**（Issue #12 仅 heads-up）
- [ ] **位置编码**：按钮/盲注位置未编码 — **推迟**
- **参考**: `state_encoder._active_player_chips_bb()`

### Gap 5: 动作空间版本锁定
- [x] **动作空间版本**：5-action 抽象与 RLCard `no-limit-holdem` 一致（FOLD/CHECK_CALL/RAISE_HALF/RAISE_POT/ALL_IN）
- [x] **加注额量化**：半池/满池/全下与 `MirrorAdapter.rlcard_action_to_engine` 一致
- **参考**: `mirror_adapter.py` 动作常量

## 审计签名

| 日期 | 审计人 | 变更 |
|------|--------|------|
| 2026-07-05 | initial | Phase A 基线；5 项 gaps 待关闭 |
| 2026-07-05 | #12 | Phase B：`state_encoder` 对齐 RLCard env；Gap 3/5 关闭；Gap 1/2/4 显式推迟或接受 |
