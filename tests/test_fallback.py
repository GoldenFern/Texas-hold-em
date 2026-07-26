"""LLM 失败降级测试 —— LLM 不可用/解析失败时规则引擎兜底。"""

from __future__ import annotations

import pytest

from src.engine.game import GameState
from src.engine.player import Player
from src.llm.config import LLMConfig, ProviderConfig
from src.llm.llm_bot import LLMBot


def make_game() -> GameState:
    players = [Player(name=f"P{i}", chips=1000, seat=i) for i in range(3)]
    game = GameState(players, small_blind=5, big_blind=10, seed=5)
    game.start_new_hand()
    return game


def mock_config() -> LLMConfig:
    cfg = LLMConfig()
    cfg.primary = ProviderConfig(provider="mock", model="mock")
    return cfg


class TestRuleFallback:
    def test_no_chain_falls_back_to_rules(self) -> None:
        """ChatModel 创建失败 → 每次决策走规则引擎,动作合法。"""
        cfg = LLMConfig()
        cfg.primary = ProviderConfig(provider="unknown-provider", model="x")
        bot = LLMBot("L1", cfg, seed=1)
        assert bot._chain_wrapper is None

        game = make_game()
        p = game.players[game.current_player_index]
        action = bot.decide(game, p)
        assert action.action_type in game.get_legal_actions(p)
        assert bot.rule_decisions == 1
        assert bot.llm_decisions == 0

    def test_mock_llm_decision_counts(self) -> None:
        """mock Provider 返回合法 JSON → 记为 LLM 决策。"""
        bot = LLMBot("L1", mock_config(), seed=1)
        game = make_game()
        p = game.players[game.current_player_index]
        action = bot.decide(game, p)
        assert action.action_type in game.get_legal_actions(p)
        assert bot.llm_decisions == 1

    def test_bad_json_falls_back(self) -> None:
        """LLM 返回坏 JSON → 解析失败 → 规则兜底,失败上下文可见。"""
        from src.llm.langchain_client import LCChainWrapper, build_fake_chat_model
        from src.llm.prompt_builder import PromptBuilder

        bot = LLMBot("L1", mock_config(), seed=1)
        fake = build_fake_chat_model(["这不是 JSON,无法解析"])
        chain = PromptBuilder.get_decision_prompt_template() | fake
        bot._chain_wrapper = LCChainWrapper(chain, bot._llm_config.primary)

        game = make_game()
        p = game.players[game.current_player_index]
        action = bot.decide(game, p)
        assert action.action_type in game.get_legal_actions(p)
        assert bot.rule_decisions == 1
        # L4 回归:失败调用也缓存上下文供调试面板
        assert bot.last_llm_context
        assert "失败" in bot.last_llm_context.get("parsed_action", "")

    def test_last_error_type_empty_on_success(self) -> None:
        bot = LLMBot("L1", mock_config(), seed=1)
        game = make_game()
        p = game.players[game.current_player_index]
        bot.decide(game, p)
        assert bot.last_error_type == ""
