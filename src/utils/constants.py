"""德州扑克游戏常量与枚举定义."""

from enum import IntEnum, Enum


class Suit(IntEnum):
    """扑克牌花色（按桥牌排序：S > H > D > C）。"""

    CLUBS = 0
    DIAMONDS = 1
    HEARTS = 2
    SPADES = 3

    @property
    def symbol(self) -> str:
        symbols = {0: "♣", 1: "♦", 2: "♥", 3: "♠"}
        return symbols[self.value]

    @property
    def short(self) -> str:
        return self.name[0]

    def __str__(self) -> str:
        return self.symbol


class Rank(IntEnum):
    """扑克牌点数（2–14，Ace=14）。"""

    TWO = 2
    THREE = 3
    FOUR = 4
    FIVE = 5
    SIX = 6
    SEVEN = 7
    EIGHT = 8
    NINE = 9
    TEN = 10
    JACK = 11
    QUEEN = 12
    KING = 13
    ACE = 14

    @property
    def short(self) -> str:
        names = {
            14: "A", 13: "K", 12: "Q", 11: "J", 10: "T",
            9: "9", 8: "8", 7: "7", 6: "6", 5: "5",
            4: "4", 3: "3", 2: "2",
        }
        return names[self.value]

    def __str__(self) -> str:
        return self.short


class HandRank(IntEnum):
    """德州扑克牌型等级（越大越好）。"""

    HIGH_CARD = 0
    ONE_PAIR = 1
    TWO_PAIR = 2
    THREE_OF_A_KIND = 3
    STRAIGHT = 4
    FLUSH = 5
    FULL_HOUSE = 6
    FOUR_OF_A_KIND = 7
    STRAIGHT_FLUSH = 8
    ROYAL_FLUSH = 9

    @property
    def display_name(self) -> str:
        names = {
            0: "高牌",
            1: "一对",
            2: "两对",
            3: "三条",
            4: "顺子",
            5: "同花",
            6: "葫芦",
            7: "四条",
            8: "同花顺",
            9: "皇家同花顺",
        }
        return names[self.value]


class PlayerStatus(IntEnum):
    """玩家状态。"""

    ACTIVE = 0       # 正常参与
    FOLDED = 1       # 已弃牌
    ALL_IN = 2       # 已全下
    OUT = 3          # 已淘汰（无筹码）


class GamePhase(IntEnum):
    """游戏阶段。"""

    WAITING = 0      # 等待开始
    PRE_FLOP = 1     # 翻牌前
    FLOP = 2         # 翻牌
    TURN = 3         # 转牌
    RIVER = 4        # 河牌
    SHOWDOWN = 5     # 摊牌
    FINISHED = 6     # 本局结束


class BettingStructure(Enum):
    """下注结构。"""

    NO_LIMIT = "no_limit"
    POT_LIMIT = "pot_limit"
    FIXED_LIMIT = "fixed_limit"


class ActionType(IntEnum):
    """玩家动作类型。"""

    FOLD = 0
    CHECK = 1
    CALL = 2
    BET = 3
    RAISE = 4
    ALL_IN = 5

    def requires_amount(self) -> bool:
        """是否需要指定金额。"""
        return self in (ActionType.BET, ActionType.RAISE)


# 默认游戏配置
DEFAULT_CONFIG = {
    "max_players": 9,
    "min_players": 2,
    "starting_chips": 1000,
    "small_blind": 5,
    "big_blind": 10,
    "betting_structure": BettingStructure.NO_LIMIT,
    "time_bank_seconds": 30,
    "ante": 0,
}
