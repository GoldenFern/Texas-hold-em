"""数值实验：测量排名分布律蒙特卡洛迭代耗时，确定最优 m 值。

约束：
- 总耗时 < 250ms
- 翻牌前 m 尽可能大
- 翻牌后 m = 翻牌前 m / 5
- 不查表
"""

from __future__ import annotations

import random
import time
from typing import List, Tuple

from src.engine.card import Card, Cards
from src.engine.hand import HandEvaluator
from src.utils._card_helpers import all_cards, random_hand
from src.utils.constants import HandRank, Rank, Suit

# ---- 辅助函数 ----


def _single_iteration_preflop(
    hero: Cards,
    community: Cards,
    opponent_count: int,
    rng: random.Random,
) -> int:
    """翻牌前：单次排名分布律蒙特卡洛迭代。

    返回 Hero 的排名（1=最好, N+1=最差）。
    """
    # 构建排除集合（Hero 手牌 + 已知公共牌）
    excluded: List[Card] = list(hero) + list(community)

    # 给 N 个对手随机发手牌（保证对手间不重复）
    opponents: List[List[Card]] = []
    for _ in range(opponent_count):
        opp_hand = random_hand(rng, excluded)
        opponents.append(opp_hand)
        excluded.extend(opp_hand)

    # 随机补全 5 张公共牌
    available = [c for c in all_cards() if c.short_str not in {x.short_str for x in excluded}]
    sim_board = list(community) + rng.sample(available, 5 - len(community))

    # 评估所有手牌
    hero_result = HandEvaluator.evaluate(hero + sim_board)
    opponent_results = [
        HandEvaluator.evaluate(opp + sim_board) for opp in opponents
    ]

    # 确定 Hero 排名（分数相同 = 并列）
    rank = 1
    for opp_result in opponent_results:
        if opp_result > hero_result:
            rank += 1
    return rank


def _single_iteration_postflop(
    hero: Cards,
    community: Cards,
    opponent_count: int,
    rng: random.Random,
) -> int:
    """翻牌后（3-4 张公共牌已翻）：单次排名分布律迭代。"""
    excluded: List[Card] = list(hero) + list(community)

    opponents = []
    for _ in range(opponent_count):
        opp_hand = random_hand(rng, excluded)
        opponents.append(opp_hand)
        excluded.extend(opp_hand)

    available = [c for c in all_cards() if c.short_str not in {x.short_str for x in excluded}]
    sim_board = list(community) + rng.sample(available, 5 - len(community))

    hero_result = HandEvaluator.evaluate(hero + sim_board)
    opponent_results = [
        HandEvaluator.evaluate(opp + sim_board) for opp in opponents
    ]

    rank = 1
    for opp_result in opponent_results:
        if opp_result > hero_result:
            rank += 1
    return rank


def run_benchmark(
    label: str,
    hero: Cards,
    community: Cards,
    opponent_count: int,
    warmup: int = 20,
    measure: int = 500,
) -> float:
    """运行一次 Benchmark，返回单次迭代平均耗时（秒）。"""
    rng = random.Random(42)

    # Warmup
    for _ in range(warmup):
        if len(community) == 0:
            _single_iteration_preflop(hero, community, opponent_count, rng)
        else:
            _single_iteration_postflop(hero, community, opponent_count, rng)

    # 测量
    t0 = time.perf_counter()
    for _ in range(measure):
        if len(community) == 0:
            _single_iteration_preflop(hero, community, opponent_count, rng)
        else:
            _single_iteration_postflop(hero, community, opponent_count, rng)
    elapsed = time.perf_counter() - t0

    avg_ms = (elapsed / measure) * 1000
    print(f"  {label}: {avg_ms:.4f} ms/iter  (total {elapsed*1000:.1f} ms / {measure} iters)")
    return avg_ms / 1000  # 返回秒


def main():
    print("=" * 60)
    print("德州扑克蒙特卡洛模拟 Benchmark")
    print("=" * 60)

    # 测试用 Hero 手牌
    hero = Card.from_str_multi("Ah Kh")

    # ---- 场景 1: 翻牌前, 5 个对手（最坏情况）----
    print("\n[翻牌前 - 0 张公共牌]")
    t_preflop_5 = run_benchmark("5 个对手", hero, [], 5)
    t_preflop_3 = run_benchmark("3 个对手", hero, [], 3)
    t_preflop_1 = run_benchmark("1 个对手", hero, [], 1)

    # ---- 场景 2: 翻牌, 5 个对手 ----
    print("\n[翻牌 - 3 张公共牌]")
    flop = Card.from_str_multi("2d 7h Kc")
    t_flop_5 = run_benchmark("5 个对手", hero, flop, 5)

    # ---- 场景 3: 转牌, 5 个对手 ----
    print("\n[转牌 - 4 张公共牌]")
    turn = Card.from_str_multi("2d 7h Kc 4s")
    t_turn_5 = run_benchmark("5 个对手", hero, turn, 5)

    # ---- 反推 m 值 ----
    # 使用翻牌前 5 对手（最坏情况）的耗时作为基准
    # m * t_preflop（牌型概率）+ m * t_preflop（排名分布律）= 总耗时需 < 250ms
    # 即：2 * m * t_preflop_5 < 0.250
    target_ms = 250
    t_worst = t_preflop_5  # 秒

    # 两个蒙特卡洛计算：牌型概率 + 排名分布律，共享一次模拟
    # 实际只跑一轮 m 次模拟，同时收集两类数据
    # 所以总耗时 = m * t_worst
    max_m_preflop = int(target_ms / 1000 / t_worst)
    m_postflop = max(1, max_m_preflop // 5)

    print("\n" + "=" * 60)
    print("分析结果")
    print("=" * 60)
    print(f"  翻牌前单次迭代 (5 对手, 最坏): {t_worst*1000:.4f} ms")
    print(f"  翻牌后单次迭代 (5 对手, 最坏): {t_flop_5*1000:.4f} ms")
    print()
    print(f"  目标总耗时: < {target_ms} ms")
    print(f"  推荐翻牌前 m: {max_m_preflop}")
    print(f"  推荐翻牌后 m: {m_postflop}  (= {max_m_preflop} / 5)")
    print()
    estimated_total = max_m_preflop * t_worst * 1000
    print(f"  预估翻牌前总耗时: {estimated_total:.1f} ms")
    estimated_postflop = m_postflop * t_flop_5 * 1000
    print(f"  预估翻牌后总耗时: {estimated_postflop:.1f} ms")

    if estimated_total > target_ms:
        print(f"\n  ⚠ 警告: 预估耗时 {estimated_total:.1f} ms 超过目标 {target_ms} ms")
        # 修正
        max_m_preflop = max(100, int(target_ms / 1000 / t_worst * 0.9))
        m_postflop = max(1, max_m_preflop // 5)
        print(f"  已修正: m_preflop={max_m_preflop}, m_postflop={m_postflop}")

    print("\n" + "=" * 60)
    print(f"最终推荐：m_preflop = {max_m_preflop}, m_postflop = {m_postflop}")
    print("=" * 60)

    # 写入结果文件供后续使用
    import os
    result_path = os.path.join(os.path.dirname(__file__), "..", "src", "analysis", "_benchmark_result.py")
    with open(result_path, "w", encoding="utf-8") as f:
        f.write(f"# Auto-generated by scripts/benchmark_sim.py\n")
        f.write(f"# Do not edit manually.\n\n")
        f.write(f"M_PREFLOP = {max_m_preflop}\n")
        f.write(f"M_POSTFLOP = {m_postflop}\n")
        f.write(f"TARGET_MS = {target_ms}\n")
    print(f"\n结果已保存至: src/analysis/_benchmark_result.py")


if __name__ == "__main__":
    main()
