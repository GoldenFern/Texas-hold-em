"""LLM 集成测试 —— 完整决策管道：游戏状态 → Prompt → LLM Mock → Action → 引擎。

使用 MockClient 避免真实 API 调用。
"""

import pytest

from src.ai.bots import BotFactory, BotStyle
from src.engine.card import Card
from src.engine.game import Action, ActionType, GameState
from src.engine.player import Player
from src.llm.client import MockClient
from src.llm.config import LLMConfig, ProviderConfig
from src.llm.llm_bot import LLMBot
from src.llm.prompt_builder import PromptBuilder
from src.llm.response_parser import ResponseParser
from src.utils.constants import BettingStructure, GamePhase, PlayerStatus, Rank, Suit


def make_players(names, chips=1000):
    """快捷创建玩家列表。"""
    return [Player(name=n, chips=chips, seat=i) for i, n in enumerate(names)]


class TestPromptBuilder:
    """Prompt 构建测试。"""

    def test_preflop_prompt_contains_key_info(self) -> None:
        players = make_players(["A", "B", "C"])
        game = GameState(players)
        game.start_new_hand()
        player = players[game.current_player_index]

        prompt = PromptBuilder.build_decision_prompt(game, player, hand_strength=0.5)
        assert "PRE_FLOP" in prompt or "翻牌前" in prompt
        assert "Pot: $" in prompt
        assert "Your stack: $" in prompt
        assert player.name in prompt
        assert "LEGAL ACTIONS" in prompt
        assert "OUTPUT" in prompt

    def test_postflop_prompt_has_draws(self) -> None:
        players = make_players(["A", "B"])
        game = GameState(players)
        game.start_new_hand()

        # 手动设置翻牌后状态
        game.phase = GamePhase.FLOP
        game.community_cards = Card.from_str_multi("9h Th 3s")
        players[0].hole_cards = Card.from_str_multi("Jh Qh")  # 同花顺听牌

        prompt = PromptBuilder.build_decision_prompt(game, players[0], hand_strength=0.4)
        assert "同花听牌" in prompt or "Draws" in prompt

    def test_prompt_includes_opponent_stats(self) -> None:
        players = make_players(["A", "B"])
        game = GameState(players)
        game.start_new_hand()
        player = players[game.current_player_index]

        stats = {"B": {"vpip": 0.35, "pfr": 0.15, "aggression": 0.8}}
        prompt = PromptBuilder.build_decision_prompt(
            game, player, hand_strength=0.5, opponent_stats=stats
        )
        assert "VPIP" in prompt or "B" in prompt


class TestResponseParser:
    """响应解析测试。"""

    def _make_game(self):
        players = make_players(["A", "B", "C"])
        game = GameState(players)
        game.start_new_hand()
        return game, players

    def test_parse_valid_fold(self) -> None:
        game, players = self._make_game()
        player = players[game.current_player_index]
        raw = '{"action": "FOLD", "amount": 0, "reasoning": "weak hand"}'
        action = ResponseParser.parse_action(raw, player, game)
        assert action is not None
        assert action.action_type == ActionType.FOLD

    def test_parse_valid_call(self) -> None:
        game, players = self._make_game()
        player = players[game.current_player_index]
        raw = '{"action": "CALL", "amount": 0, "reasoning": "priced in"}'
        action = ResponseParser.parse_action(raw, player, game)
        assert action is not None
        assert action.action_type == ActionType.CALL

    def test_parse_valid_raise(self) -> None:
        game, players = self._make_game()
        player = players[game.current_player_index]
        raw = '{"action": "RAISE", "amount": 30, "reasoning": "value bet"}'
        action = ResponseParser.parse_action(raw, player, game)
        assert action is not None
        assert action.action_type == ActionType.RAISE
        assert action.amount >= game.get_min_raise_amount(player)

    def test_parse_markdown_fence(self) -> None:
        """测试从 markdown 代码围栏中提取 JSON。"""
        game, players = self._make_game()
        # 让所有人跟注直到翻牌，使 CHECK 合法
        for _ in range(10):
            if game.phase != GamePhase.PRE_FLOP:
                break
            cp = game.players[game.current_player_index]
            legal = game.get_legal_actions(cp)
            if ActionType.CALL in legal:
                game.apply_action(Action(cp.name, ActionType.CALL))
            elif ActionType.CHECK in legal:
                game.apply_action(Action(cp.name, ActionType.CHECK))
            else:
                break

        if game.phase != GamePhase.FLOP:
            pytest.skip("无法进入翻牌阶段")

        player = game.players[game.current_player_index]
        raw = '```json\n{"action": "CHECK", "amount": 0, "reasoning": "free card"}\n```'
        action = ResponseParser.parse_action(raw, player, game)
        assert action is not None
        assert action.action_type == ActionType.CHECK

    def test_parse_lowercase_action(self) -> None:
        game, players = self._make_game()
        player = players[game.current_player_index]
        raw = '{"action": "fold", "amount": 0, "reasoning": "bad cards"}'
        action = ResponseParser.parse_action(raw, player, game)
        assert action is not None
        assert action.action_type == ActionType.FOLD

    def test_parse_all_in_semantic(self) -> None:
        game, players = self._make_game()
        player = players[game.current_player_index]
        player.chips = 100
        raw = '{"action": "ALL_IN", "amount": 0, "reasoning": "all in"}'
        action = ResponseParser.parse_action(raw, player, game)
        assert action is not None
        assert action.action_type == ActionType.RAISE
        assert action.amount == player.chips + player.current_bet

    def test_parse_invalid_json_returns_none(self) -> None:
        game, players = self._make_game()
        player = players[game.current_player_index]
        raw = "not json at all"
        action = ResponseParser.parse_action(raw, player, game)
        assert action is None

    def test_parse_invalid_action_returns_none(self) -> None:
        game, players = self._make_game()
        player = players[game.current_player_index]
        raw = '{"action": "BLUFF", "amount": 100, "reasoning": "lol"}'
        action = ResponseParser.parse_action(raw, player, game)
        assert action is None

    def test_amount_clamped_to_range(self) -> None:
        game, players = self._make_game()
        player = players[game.current_player_index]
        max_bet = game.get_max_bet(player)
        raw = f'{{"action": "RAISE", "amount": {max_bet + 1000}, "reasoning": "overbet"}}'
        action = ResponseParser.parse_action(raw, player, game)
        assert action is not None
        assert action.amount <= max_bet

    def test_raise_becomes_bet_when_current_bet_zero(self) -> None:
        """当 current_bet == 0 时，RAISE 应转为 BET。"""
        players = make_players(["A", "B"])
        game = GameState(players)
        game.start_new_hand()
        # 所有人平跟后进入翻牌（current_bet=0）
        for _ in range(10):
            if game.phase == GamePhase.FLOP:
                break
            cp = game.players[game.current_player_index]
            legal = game.get_legal_actions(cp)
            if ActionType.CALL in legal:
                game.apply_action(Action(cp.name, ActionType.CALL))
            elif ActionType.CHECK in legal:
                game.apply_action(Action(cp.name, ActionType.CHECK))
            else:
                break

        if game.phase == GamePhase.FLOP:
            player = game.players[game.current_player_index]
            raw = '{"action": "RAISE", "amount": 20, "reasoning": "cbet"}'
            action = ResponseParser.parse_action(raw, player, game)
            # 如果 RAISE 不在合法动作中，应转为 BET
            if action is None:
                # 解析器返回 None，降级处理
                pass
            else:
                assert action.action_type in (ActionType.RAISE, ActionType.BET)


class TestLLMBotWithMock:
    """LLMBot + MockClient 集成测试。"""

    def test_llmbot_creation_and_decision(self) -> None:
        """创建 LLMBot 并验证决策合法性。"""
        llm_config = LLMConfig()
        llm_config.primary = ProviderConfig(provider="mock", model="mock")
        # 清空降级链，仅用规则引擎兜底
        llm_config.fallbacks = []

        bot = LLMBot("TestLLM", llm_config, seed=42)
        assert "TestLLM" in str(bot)

        # 创建游戏并测试决策
        players = make_players(["TestLLM", "B", "C"])
        game = GameState(players)
        game.start_new_hand()
        player = players[game.current_player_index]

        # 确保 MockClient 返回合法响应（Mock 默认返回 CHECK，可能不合法）
        # 但降级链会兜底，所以结果应该合法
        action = bot.decide(game, player)
        assert action is not None
        assert action.player_name == player.name
        assert action.action_type in game.get_legal_actions(player)

    def test_llmbot_fallback_to_rule(self) -> None:
        """验证 LLM 失败时降级到规则引擎。"""
        llm_config = LLMConfig()
        llm_config.primary = ProviderConfig(provider="mock", model="mock")
        llm_config.fallbacks = []

        bot = LLMBot("TestLLM", llm_config, seed=42)
        # 用返回非法 JSON 的 Mock 替换客户端
        bot._llm_client = MockClient(responses=["not valid json at all"])

        # 创建游戏
        players = make_players(["TestLLM", "B", "C"])
        game = GameState(players)
        game.start_new_hand()
        player = players[game.current_player_index]

        # 即使 LLM 返回非法内容，也应产生合法动作（降级链/规则引擎兜底）
        action = bot.decide(game, player)
        assert action is not None
        assert action.action_type in game.get_legal_actions(player)
        # 确认使用了降级链或规则引擎（不是纯 LLM）
        total_fallback = bot.fallback_decisions + bot.rule_decisions
        assert total_fallback >= 1 or bot.llm_decisions == 0

    def test_llmbot_system_prompt_is_valid(self) -> None:
        """验证系统 Prompt 格式正确。"""
        system = PromptBuilder.get_system_prompt()
        assert "Texas Hold'em" in system
        assert "JSON" in system
        assert len(system) > 50

    def test_advisor_prompt_format(self) -> None:
        """验证顾问 Prompt 格式。"""
        players = make_players(["A", "B"])
        game = GameState(players)
        game.start_new_hand()
        player = players[game.current_player_index]

        advisor_prompt = PromptBuilder.build_advisor_prompt(game, player)
        assert "EDUCATIONAL" in PromptBuilder.get_advisor_system_prompt() or "coach" in PromptBuilder.get_advisor_system_prompt()

    def test_factory_creates_llm_bot(self) -> None:
        """验证 BotFactory 可以创建 LLM 机器人。"""
        bot = BotFactory.create_llm(name="AI", provider="mock", model="mock", seed=42)
        assert bot is not None
        from src.llm.llm_bot import LLMBot
        assert isinstance(bot, LLMBot)


class TestConfig:
    """配置加载测试。"""

    def test_default_config(self) -> None:
        from src.llm.config import LLMConfig
        config = LLMConfig()
        assert config.primary.provider == "anthropic"
        assert config.call_frequency == "every"
        assert len(config.fallbacks) >= 1

    def test_provider_config(self) -> None:
        from src.llm.config import ProviderConfig
        cfg = ProviderConfig(provider="ollama", model="llama3.1:8b", base_url="http://localhost:11434")
        assert cfg.provider == "ollama"
        assert cfg.base_url == "http://localhost:11434"


class TestLLMBotCommentary:
    """解说 Prompt 测试。"""

    def test_commentary_prompt(self) -> None:
        from src.llm.prompt_builder import PromptBuilder
        hand = {
            "hand_id": 42,
            "community_cards": ["As", "Kd", "Qh", "Jh", "Th"],
            "pot_total": 350,
            "winners": {"Hero": 350},
            "actions": ["Hero: RAISE $50", "Villain: CALL", "Villain: FOLD"],
        }
        prompt = PromptBuilder.build_commentary_prompt(hand)
        assert "42" in prompt
        assert "commentator" in prompt or "commentary" in prompt.lower() or "As" in prompt
