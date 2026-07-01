"""Card / Suit / Rank 单元测试。"""

import pytest

from src.engine.card import Card
from src.utils.constants import Rank, Suit


class TestSuit:
    """花色测试。"""

    def test_suit_count(self) -> None:
        assert len(Suit) == 4

    def test_suit_symbols(self) -> None:
        assert Suit.CLUBS.symbol == "♣"
        assert Suit.DIAMONDS.symbol == "♦"
        assert Suit.HEARTS.symbol == "♥"
        assert Suit.SPADES.symbol == "♠"

    def test_suit_ordering(self) -> None:
        """桥牌花色排序：C < D < H < S。"""
        assert Suit.CLUBS < Suit.DIAMONDS
        assert Suit.DIAMONDS < Suit.HEARTS
        assert Suit.HEARTS < Suit.SPADES


class TestRank:
    """点数测试。"""

    def test_rank_values(self) -> None:
        assert Rank.TWO == 2
        assert Rank.TEN == 10
        assert Rank.ACE == 14

    def test_rank_ordering(self) -> None:
        assert Rank.TWO < Rank.THREE
        assert Rank.KING < Rank.ACE
        assert Rank.ACE > Rank.TWO

    def test_rank_short_names(self) -> None:
        assert Rank.ACE.short == "A"
        assert Rank.KING.short == "K"
        assert Rank.QUEEN.short == "Q"
        assert Rank.JACK.short == "J"
        assert Rank.TEN.short == "T"
        assert Rank.TWO.short == "2"


class TestCard:
    """纸牌测试。"""

    def test_card_creation(self) -> None:
        card = Card(rank=Rank.ACE, suit=Suit.SPADES)
        assert card.rank == Rank.ACE
        assert card.suit == Suit.SPADES

    def test_card_immutable(self) -> None:
        card = Card(rank=Rank.KING, suit=Suit.HEARTS)
        with pytest.raises(Exception):
            card.rank = Rank.ACE  # type: ignore[misc]

    def test_from_str_single(self) -> None:
        card = Card.from_str("Ah")
        assert card.rank == Rank.ACE
        assert card.suit == Suit.HEARTS

    def test_from_str_all_ranks(self) -> None:
        """测试所有 rank 的字符串解析。"""
        for rank_char, rank_enum in [
            ("2", Rank.TWO), ("3", Rank.THREE), ("4", Rank.FOUR),
            ("5", Rank.FIVE), ("6", Rank.SIX), ("7", Rank.SEVEN),
            ("8", Rank.EIGHT), ("9", Rank.NINE), ("T", Rank.TEN),
            ("J", Rank.JACK), ("Q", Rank.QUEEN), ("K", Rank.KING),
            ("A", Rank.ACE),
        ]:
            card = Card.from_str(f"{rank_char}h")
            assert card.rank == rank_enum, f"Failed for {rank_char}"

    def test_from_str_all_suits(self) -> None:
        """测试所有花色的字符串解析。"""
        for suit_char, suit_enum in [
            ("c", Suit.CLUBS), ("d", Suit.DIAMONDS),
            ("h", Suit.HEARTS), ("s", Suit.SPADES),
        ]:
            card = Card.from_str(f"A{suit_char}")
            assert card.suit == suit_enum, f"Failed for {suit_char}"

    def test_from_str_case_insensitive(self) -> None:
        assert Card.from_str("aS") == Card(rank=Rank.ACE, suit=Suit.SPADES)
        assert Card.from_str("aH") == Card(rank=Rank.ACE, suit=Suit.HEARTS)

    def test_from_str_invalid(self) -> None:
        with pytest.raises(ValueError):
            Card.from_str("Xh")
        with pytest.raises(ValueError):
            Card.from_str("Ax")
        with pytest.raises(ValueError):
            Card.from_str("")

    def test_from_str_multi(self) -> None:
        cards = Card.from_str_multi("Ah Kd Qs")
        assert len(cards) == 3
        assert cards[0] == Card(rank=Rank.ACE, suit=Suit.HEARTS)
        assert cards[1] == Card(rank=Rank.KING, suit=Suit.DIAMONDS)
        assert cards[2] == Card(rank=Rank.QUEEN, suit=Suit.SPADES)

    def test_from_str_multi_empty(self) -> None:
        assert Card.from_str_multi("") == []
        assert Card.from_str_multi("   ") == []

    def test_card_comparison(self) -> None:
        """牌仅按点数比较。"""
        ace_spades = Card(rank=Rank.ACE, suit=Suit.SPADES)
        ace_hearts = Card(rank=Rank.ACE, suit=Suit.HEARTS)
        king = Card(rank=Rank.KING, suit=Suit.SPADES)
        assert ace_spades > king
        assert ace_spades != ace_hearts  # 不同花色，不是同一张牌
        assert not (ace_spades < ace_hearts)  # 仅按点数比较
        assert not (ace_spades > ace_hearts)  # 点数相同
        assert king < ace_hearts

    def test_card_string_representation(self) -> None:
        card = Card(rank=Rank.ACE, suit=Suit.SPADES)
        assert str(card) == "A♠"
        assert card.short_str == "As"

    def test_card_equality(self) -> None:
        c1 = Card(rank=Rank.ACE, suit=Suit.SPADES)
        c2 = Card(rank=Rank.ACE, suit=Suit.SPADES)
        c3 = Card(rank=Rank.ACE, suit=Suit.HEARTS)
        assert c1 == c2
        assert c1 != c3

    def test_all_52_cards_unique(self) -> None:
        """生成全部 52 张牌，确保每张唯一。"""
        from itertools import product
        cards = [Card(rank=r, suit=s) for r, s in product(Rank, Suit)]
        assert len(cards) == 52
        assert len(set(cards)) == 52
