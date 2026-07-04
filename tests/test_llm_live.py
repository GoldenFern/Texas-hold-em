"""LLM 实机调用集成测试 —— 使用真实 API 验证完整决策管道。

需要设置对应的环境变量（DEEPSEEK_API_KEY 等）。
未设置时自动跳过。
"""

import os
import json
import time
import pytest

import requests

from src.llm.prompt_builder import PromptBuilder
from src.llm.response_parser import ResponseParser
from src.engine.game import Action, ActionType, GameState
from src.engine.player import Player
from src.engine.card import Card
from src.utils.constants import GamePhase


# ================================================================
# 辅助
# ================================================================

def _make_game_for_player(player_name: str = "Hero"):
    """创建基础游戏状态用于 prompt 构建。"""
    names = [player_name, "Villain1", "Villain2"]
    players = [Player(name=n, chips=1000, seat=i) for i, n in enumerate(names)]
    game = GameState(players, small_blind=5, big_blind=10)
    game.start_new_hand()
    return game, players


def _call_deepseek(
    prompt: str,
    system_prompt: str = "",
    model: str = "deepseek-v4-flash",
    max_tokens: int = 262144,
    temperature: float = 0.1,
    timeout: int = 60,
) -> dict:
    """直接调用 DeepSeek API（使用 requests，绕过 httpx 代理问题）。"""
    api_key = os.environ["DEEPSEEK_API_KEY"]
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }
    messages = []
    if system_prompt:
        messages.append({"role": "system", "content": system_prompt})
    messages.append({"role": "user", "content": prompt})

    payload = {
        "model": model,
        "messages": messages,
        "max_tokens": max_tokens,
        "temperature": temperature,
    }

    start = time.perf_counter()
    resp = requests.post(
        "https://api.deepseek.com/v1/chat/completions",
        headers=headers,
        json=payload,
        timeout=timeout,
    )
    latency = time.perf_counter() - start
    resp.raise_for_status()
    data = resp.json()
    return {
        "text": data["choices"][0]["message"]["content"],
        "latency": round(latency, 2),
        "model": data.get("model", model),
    }


# ================================================================
# DeepSeek live test
# ================================================================

@pytest.mark.skipif(
    not os.environ.get("DEEPSEEK_API_KEY"),
    reason="DEEPSEEK_API_KEY 未设置",
)
class TestDeepSeekLive:
    """DeepSeek 实机调用测试。"""

    def test_deepseek_v4_flash_basic_call(self) -> None:
        """基本调用：发送简单 prompt，验证返回格式。"""
        result = _call_deepseek(
            prompt="Say 'poker' in one word. Just the word, nothing else.",
            max_tokens=20,
        )
        assert len(result["text"]) > 0
        assert result["latency"] > 0
        print(f"\n[DeepSeek Basic] ({result['latency']}s): {result['text']}")

    def test_deepseek_v4_flash_poker_decision(self) -> None:
        """发送德州扑克决策 prompt，验证返回合法的 JSON 动作。"""
        game, players = _make_game_for_player("Hero")
        player = players[game.current_player_index]
        player.hole_cards = Card.from_str_multi("Ah Kh")

        system_prompt = PromptBuilder.get_system_prompt()
        prompt = PromptBuilder.build_decision_prompt(
            game, player,
            hand_strength=70,
            equity_pct=65.0,
        )

        result = _call_deepseek(prompt, system_prompt)
        print(f"\n[DeepSeek Decision] ({result['latency']}s):\n{result['text']}")

        action = ResponseParser.parse_action(result["text"], player, game)
        legal = game.get_legal_actions(player)
        assert action is not None, (
            f"DeepSeek 返回了无法解析的响应:\n{result['text']}\n"
            f"合法动作: {[a.name for a in legal]}"
        )
        assert action.action_type in legal, (
            f"DeepSeek 返回了非法动作 {action.action_type.name}, "
            f"合法: {[a.name for a in legal]}"
        )
        print(f"  -> Parsed action: {action.action_type.name} (amount={action.amount})")

    def test_deepseek_v4_flash_postflop_decision(self) -> None:
        """翻牌后决策：有顶对顶踢脚，应能做出合理决策。"""
        game, players = _make_game_for_player("Hero")
        player = players[game.current_player_index]
        player.hole_cards = Card.from_str_multi("Ah Kh")
        game.community_cards = Card.from_str_multi("Kd 7s 2c")
        game.phase = GamePhase.FLOP
        game.current_bet = 0

        system_prompt = PromptBuilder.get_system_prompt()
        prompt = PromptBuilder.build_decision_prompt(
            game, player,
            hand_strength=85,
            equity_pct=80.0,
        )

        result = _call_deepseek(prompt, system_prompt)
        print(f"\n[DeepSeek Postflop] ({result['latency']}s):\n{result['text']}")

        action = ResponseParser.parse_action(result["text"], player, game)
        legal = game.get_legal_actions(player)
        assert action is not None, (
            f"DeepSeek postflop 返回了无法解析的响应:\n{result['text']}"
        )
        assert action.action_type in legal, (
            f"DeepSeek postflop 返回了非法动作 {action.action_type.name}, "
            f"合法: {[a.name for a in legal]}"
        )
        print(f"  -> Parsed action: {action.action_type.name} (amount={action.amount})")

    def test_deepseek_v4_flash_reasoning_included(self) -> None:
        """验证返回的 JSON 中包含 reasoning 字段。"""
        game, players = _make_game_for_player("Hero")
        player = players[game.current_player_index]
        player.hole_cards = Card.from_str_multi("Ah Kh")

        system_prompt = PromptBuilder.get_system_prompt()
        prompt = PromptBuilder.build_decision_prompt(
            game, player,
            hand_strength=70,
            equity_pct=65.0,
        )

        result = _call_deepseek(prompt, system_prompt)
        print(f"\n[DeepSeek Reasoning] ({result['latency']}s):\n{result['text']}")

        reasoning = ResponseParser.extract_reasoning(result["text"])
        assert reasoning is not None and len(reasoning) > 0, (
            f"DeepSeek 返回的响应缺少 reasoning:\n{result['text']}"
        )
        print(f"  -> Reasoning: {reasoning[:100]}...")

    def test_deepseek_v4_flash_call_when_facing_raise(self) -> None:
        """面对加注时的决策：AKs 面对 3-bet 应跟注或再加注，不应弃牌。"""
        game, players = _make_game_for_player("Hero")
        player = players[game.current_player_index]
        player.hole_cards = Card.from_str_multi("Ah Kh")
        # 模拟对手加注到 30
        game.current_bet = 30

        system_prompt = PromptBuilder.get_system_prompt()
        prompt = PromptBuilder.build_decision_prompt(
            game, player,
            hand_strength=70,
            equity_pct=65.0,
        )

        result = _call_deepseek(prompt, system_prompt)
        print(f"\n[DeepSeek vs Raise] ({result['latency']}s):\n{result['text']}")

        action = ResponseParser.parse_action(result["text"], player, game)
        legal = game.get_legal_actions(player)
        assert action is not None, f"DeepSeek 返回无法解析的响应:\n{result['text']}"
        assert action.action_type in legal, (
            f"DeepSeek 返回非法动作 {action.action_type.name}, 合法: {[a.name for a in legal]}"
        )
        # AKs 面对 3-bet 不应弃牌
        assert action.action_type != ActionType.FOLD, (
            f"AKs 不应弃牌，但 DeepSeek 选择 FOLD:\n{result['text']}"
        )
        print(f"  -> Parsed action: {action.action_type.name} (amount={action.amount})")
