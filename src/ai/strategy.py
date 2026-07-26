"""AI 策略引擎 —— 翻前查表与翻后实时胜率。

翻牌前胜率查预生成的多人胜率表（scripts/build_preflop_table.py 离线生成,
惰性加载）;翻牌后用 Treys 快速通道做实时 Monte Carlo。
平局约定统一为 equity share。
"""

from __future__ import annotations

import json
import logging
import os
import random
import zlib
from typing import Dict, List, Optional, Tuple

from src.engine.card import Cards
from src.engine.hand import HandEvaluator
from src.utils._card_helpers import count_outs, detect_draws, treys_ids, treys_pool

logger = logging.getLogger(__name__)

_EQUITY_CACHE_FILE = os.path.join(os.path.dirname(__file__), "preflop_equity.json")
_MAX_OPPONENTS = 8

# 惰性加载的多人胜率表: (high, low, suited) -> [w_vs1, ..., w_vs8]
_PREFLOP_EQUITY: Optional[Dict[Tuple[int, int, bool], List[float]]] = None


def _load_table() -> Dict[Tuple[int, int, bool], List[float]]:
    """加载翻前胜率表（仅首次调用时读文件）。

    Raises:
        FileNotFoundError: 表文件缺失（需先运行生成脚本）。
        ValueError: 表文件是旧版单人格式或已损坏。
    """
    global _PREFLOP_EQUITY
    if _PREFLOP_EQUITY is not None:
        return _PREFLOP_EQUITY

    if not os.path.isfile(_EQUITY_CACHE_FILE):
        raise FileNotFoundError(
            f"翻前胜率表缺失: {_EQUITY_CACHE_FILE}\n"
            "请先运行: python scripts/build_preflop_table.py"
        )
    with open(_EQUITY_CACHE_FILE, "r", encoding="utf-8") as f:
        raw = json.load(f)
    if not isinstance(raw, dict) or "table" not in raw:
        raise ValueError(
            "翻前胜率表为旧版格式，请重新生成: "
            "python scripts/build_preflop_table.py"
        )

    table: Dict[Tuple[int, int, bool], List[float]] = {}
    for key_str, values in raw["table"].items():
        h, l, s = key_str.split(",")
        table[(int(h), int(l), s == "1")] = list(values)

    logger.info("翻前胜率表已加载: %d 种手牌 × vs 1..%d 对手",
                len(table), _MAX_OPPONENTS)
    _PREFLOP_EQUITY = table
    return table


# ================================================================
# 翻牌前手牌强度 —— 多人真实胜率查表
# ================================================================

def preflop_hand_strength(cards: Cards, n_opponents: int = 1) -> float:
    """翻牌前 equity share（0–100）,查多人胜率表。

    Args:
        cards: 两张底牌。
        n_opponents: 对手数量（1–8, 越界自动钳位）。

    Returns:
        对阵 n 个随机对手的 equity share × 100（浮点,不截断）。
    """
    if len(cards) != 2:
        return 0.0

    r1, r2 = cards[0].rank.value, cards[1].rank.value
    suited = cards[0].suit == cards[1].suit
    key = (max(r1, r2), min(r1, r2), suited)

    table = _load_table()
    n = max(1, min(_MAX_OPPONENTS, n_opponents))
    return table[key][n - 1]


# ================================================================
# 翻牌后手牌强度 —— Treys 快速 MC（可注入 RNG）
# ================================================================

def postflop_hand_strength(
    hole_cards: Cards,
    community_cards: Cards,
    num_simulations: int = 300,
    rng: Optional[random.Random] = None,
) -> float:
    """翻牌后 equity share（0.0–1.0）, vs 1 个随机对手。

    转牌圈对全部剩余河牌精确枚举以降低方差。
    未提供 rng 时按输入状态派生确定性种子（同输入同输出）。

    Args:
        hole_cards: 底牌（2 张）。
        community_cards: 公共牌（3–5 张; 少于 3 张时回退翻前查表）。
        num_simulations: 目标模拟次数。
        rng: 可选注入的随机数生成器。

    Returns:
        0.0–1.0 的 equity share。
    """
    if len(community_cards) < 3:
        return preflop_hand_strength(hole_cards) / 100.0

    if rng is None:
        state = (
            tuple(sorted(c.short_str for c in hole_cards)),
            tuple(sorted(c.short_str for c in community_cards)),
            num_simulations,
        )
        rng = random.Random(zlib.crc32(repr(state).encode("utf-8")))

    hero = treys_ids(hole_cards)
    board_known = treys_ids(community_cards)
    pool = treys_pool(list(hole_cards) + list(community_cards))
    needed = 5 - len(board_known)

    from src.analysis.battle_analyzer import _treys  # 复用全局求值器
    evaluate = _treys.evaluate

    equity_sum = 0.0
    total = 0

    if needed == 1:
        # 转牌: 抽对手 × 精确枚举河牌
        outer = max(1, num_simulations // (len(pool) - 2))
        for _ in range(outer):
            opp = rng.sample(pool, 2)
            opp_set = set(opp)
            for river in pool:
                if river in opp_set:
                    continue
                board = board_known + [river]
                hs = evaluate(hero, board)
                os_ = evaluate(opp, board)
                if hs < os_:
                    equity_sum += 1.0
                elif hs == os_:
                    equity_sum += 0.5
                total += 1
    else:
        for _ in range(num_simulations):
            drawn = rng.sample(pool, 2 + needed)
            opp = drawn[:2]
            board = board_known + drawn[2:]
            hs = evaluate(hero, board)
            os_ = evaluate(opp, board)
            if hs < os_:
                equity_sum += 1.0
            elif hs == os_:
                equity_sum += 0.5
            total += 1

    return round(equity_sum / max(1, total), 4)


# ================================================================
# 听牌检测（委托 _card_helpers）
# ================================================================

def has_draw(hole_cards: Cards, community_cards: Cards) -> Tuple[bool, bool]:
    """检测听牌。

    Returns:
        (has_flush_draw, has_straight_draw)
    """
    if len(community_cards) < 3:
        return False, False
    return detect_draws(hole_cards, community_cards)


def draw_info(hole_cards: Cards, community_cards: Cards):
    """完整听牌信息（含 outs 计数）,供 LLM prompt 与分析面板。"""
    return count_outs(hole_cards, community_cards)


# ================================================================
# 手牌品质判定
# ================================================================

def is_premium_hand(cards: Cards) -> bool:
    """是否为顶级手牌（vs 1 对手 equity >= 70%）。

    按当前表覆盖 AA/KK/QQ/JJ/TT/99/88 等所有 >=70 的口袋对。
    """
    return preflop_hand_strength(cards) >= 70.0


def is_playable_hand(cards: Cards) -> bool:
    """是否为可玩手牌（vs 1 对手 equity >= 45%）。"""
    return preflop_hand_strength(cards) >= 45.0
