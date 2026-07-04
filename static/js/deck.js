/**
 * deck.js — 牌组皮肤注册表、路径解析与本地偏好（localStorage）。
 */

/** @type {ReadonlyArray<{id: string, label: string, ext: string, back: string, faceStyle: 'prefix2'|'suffix2'}>} */
const DECK_SKINS = [
    { id: 'aguilar',     label: '经典 PNG', ext: 'png', back: 'back.png', faceStyle: 'prefix2' },
    { id: 'aguilar_old', label: '矢量 SVG', ext: 'svg', back: 'back.png', faceStyle: 'suffix2' },
];

const DECK_STORAGE_KEY = 'thp_card_deck';

const RANK_FILE = {
    'A': 'ace', '2': '2', '3': '3', '4': '4', '5': '5', '6': '6',
    '7': '7', '8': '8', '9': '9', 'T': '10',
    'J': 'jack2', 'Q': 'queen2', 'K': 'king2',
};

const SUIT_FILE = {
    '♠': 'spades', '♥': 'hearts', '♦': 'diamonds', '♣': 'clubs',
    's': 'spades', 'h': 'hearts', 'd': 'diamonds', 'c': 'clubs',
};

const DeckSkin = {
    _index: 0,

    /** 从 localStorage 恢复偏好并绑定设置面板控件 */
    init() {
        const saved = localStorage.getItem(DECK_STORAGE_KEY);
        if (saved) {
            const idx = DECK_SKINS.findIndex((d) => d.id === saved);
            if (idx >= 0) this._index = idx;
        }
        const btn = document.getElementById('btn-cycle-deck');
        if (btn) btn.addEventListener('click', () => this.cycle());
        this._updateLabel();
    },

    /** @returns {{id: string, label: string, ext: string, back: string}} */
    current() {
        return DECK_SKINS[this._index];
    },

    /** 循环切换至下一套皮肤，立即生效并持久化 */
    cycle() {
        this._index = (this._index + 1) % DECK_SKINS.length;
        localStorage.setItem(DECK_STORAGE_KEY, this.current().id);
        this._updateLabel();
        this.refreshDisplay();
    },

    /**
     * 将服务器牌串映射为当前皮肤的图片路径。
     * @param {string|null|undefined} cardStr 如 "A♠"、"T♥"
     * @returns {string|null}
     */
    cardPath(cardStr) {
        if (!cardStr || cardStr === '??') return null;
        const deck = this.current();
        let rank = cardStr[0];
        const suitChar = cardStr[cardStr.length - 1];
        if (rank === '1' && cardStr.length >= 3) rank = '10';
        const fileRank = RANK_FILE[rank];
        const fileSuit = SUIT_FILE[suitChar];
        if (!fileRank || !fileSuit) return null;
        const stem = this._cardFileStem(rank, fileRank, fileSuit, deck.faceStyle);
        return `/static/img/cards/${deck.id}/${stem}.${deck.ext}`;
    },

    /**
     * @param {string} rank 单字符点数
     * @param {string} fileRank RANK_FILE 映射值
     * @param {string} fileSuit 花色文件名
     * @param {'prefix2'|'suffix2'} faceStyle
     */
    _cardFileStem(rank, fileRank, fileSuit, faceStyle) {
        const isFace = rank === 'J' || rank === 'Q' || rank === 'K';
        if (isFace && faceStyle === 'suffix2') {
            return `${fileRank.replace(/2$/, '')}_of_${fileSuit}2`;
        }
        return `${fileRank}_of_${fileSuit}`;
    },

    /** @returns {string} 当前皮肤的牌背路径 */
    backPath() {
        const deck = this.current();
        return `/static/img/cards/${deck.id}/${deck.back}`;
    },

    /** 切换皮肤后重绘牌桌（A1：立即生效） */
    refreshDisplay() {
        if (typeof App !== 'undefined' && App.gameState) {
            Table.render(App.gameState);
            if (typeof Controls !== 'undefined' && Controls.update) {
                Controls.update(App.gameState);
            }
        }
    },

    /** 刷新设置面板中的当前牌组标签 */
    updateUILabel() {
        this._updateLabel();
    },

    _updateLabel() {
        const el = document.getElementById('deck-skin-label');
        if (el) el.textContent = this.current().label;
    },
};

document.addEventListener('DOMContentLoaded', () => DeckSkin.init());
