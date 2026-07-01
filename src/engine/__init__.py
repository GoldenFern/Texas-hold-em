"""Core game engine module.

模块按需导入，避免循环依赖和缺失依赖。
"""

from src.engine.card import Card
from src.engine.deck import Deck
from src.engine.hand import HandEvaluator, HandRank, HandResult
from src.utils.constants import (
    ActionType,
    BettingStructure,
    GamePhase,
    PlayerStatus,
    Suit,
    Rank,
)

__all__ = [
    "Card",
    "Deck",
    "HandEvaluator", "HandRank", "HandResult",
    "ActionType", "BettingStructure", "GamePhase",
    "PlayerStatus", "Suit", "Rank",
]
