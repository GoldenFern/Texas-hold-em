"""Deck 单元测试。"""

import pytest

from src.engine.card import Card
from src.engine.deck import Deck
from src.utils.constants import Rank, Suit


class TestDeck:
    """牌堆测试。"""

    def test_new_deck_has_52_cards(self) -> None:
        deck = Deck()
        assert len(deck) == 52
        assert deck.remaining == 52

    def test_deck_unique_cards(self) -> None:
        """确保牌堆中每张牌唯一。"""
        deck = Deck()
        all_cards = list(deck)
        assert len(all_cards) == 52
        assert len(set(all_cards)) == 52

    def test_shuffle_preserves_count(self) -> None:
        deck = Deck()
        deck.shuffle()
        assert len(deck) == 52

    def test_shuffle_changes_order(self) -> None:
        """洗牌后顺序应有变化（概率极低的 flaky test，但可接受）。"""
        deck1 = Deck()
        deck1.shuffle()
        order1 = [c.short_str for c in deck1]

        deck2 = Deck()
        deck2.shuffle()
        order2 = [c.short_str for c in deck2]

        # 两次洗牌顺序完全相同的概率 ≈ 1/52!，可忽略
        assert order1 != order2

    def test_deal_reduces_count(self) -> None:
        deck = Deck()
        deck.shuffle()
        cards = deck.deal(5)
        assert len(cards) == 5
        assert len(deck) == 47

    def test_deal_one(self) -> None:
        deck = Deck()
        card = deck.deal_one()
        assert isinstance(card, Card)
        assert len(deck) == 51

    def test_deal_too_many_raises(self) -> None:
        deck = Deck()
        with pytest.raises(ValueError):
            deck.deal(53)

    def test_deal_negative_raises(self) -> None:
        deck = Deck()
        with pytest.raises(ValueError):
            deck.deal(-1)

    def test_deal_all_cards(self) -> None:
        deck = Deck()
        cards = deck.deal(52)
        assert len(cards) == 52
        assert len(deck) == 0
        assert not deck

    def test_reset_restores_deck(self) -> None:
        deck = Deck()
        deck.deal(30)
        assert len(deck) == 22
        deck.reset()
        assert len(deck) == 52

    def test_deck_contains_all_combinations(self) -> None:
        """确保牌堆包含所有 rank-suit 组合。"""
        deck = Deck()
        cards_set = {(c.rank, c.suit) for c in deck}
        from itertools import product
        expected = {(r, s) for r, s in product(Rank, Suit)}
        assert cards_set == expected
