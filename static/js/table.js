/**
 * table.js — 扑克桌面渲染：玩家位置、公共牌、底池、动画。
 * 牌面素材由 DeckSkin 注册表管理（见 deck.js）。
 */

const Table = {
    /** 根据 gameState 渲染整个桌面 */
    render(state) {
        this._renderCommunityCards(state.community_cards);
        this._renderPot(state.pot_total, state.phase, state.current_bet);
        this._renderPlayers(state);
    },

    /** @deprecated 请使用 DeckSkin.cardPath；保留供外部兼容调用 */
    _cardImgPath(cardStr) {
        return DeckSkin.cardPath(cardStr);
    },

    /** 渲染公共牌 */
    _renderCommunityCards(cards) {
        const slots = document.querySelectorAll('.community-card');
        slots.forEach((slot, i) => {
            if (i < cards.length && cards[i] !== '??') {
                slot.className = 'community-card card-revealed';
                const path = this._cardImgPath(cards[i]);
                slot.innerHTML = path ? `<img src="${path}" class="card-img" alt="${cards[i]}">` : '';
            } else {
                slot.className = 'community-card slot';
                slot.innerHTML = '';
            }
        });
    },

    /** 渲染单张牌的内容 */
    _renderCardContent(el, cardStr) {
        const path = this._cardImgPath(cardStr);
        if (path) {
            el.innerHTML = `<img src="${path}" class="card-img" alt="${cardStr}">`;
        } else {
            el.innerHTML = `<img src="${DeckSkin.backPath()}" class="card-img" alt="?">`;
        }
    },

    /** 渲染底池信息 */
    _renderPot(potTotal, phase, currentBet) {
        document.getElementById('pot-amount').textContent = `底池: $${potTotal}`;
        const phaseNames = {
            'WAITING': '等待开始', 'PRE_FLOP': '翻牌前', 'FLOP': '翻牌',
            'TURN': '转牌', 'RIVER': '河牌', 'SHOWDOWN': '摊牌', 'FINISHED': '已结束'
        };
        document.getElementById('pot-phase').textContent = phaseNames[phase] || phase;
    },

    /** 渲染玩家位置 */
    _renderPlayers(state) {
        const container = document.getElementById('players-container');
        const players = state.players;
        const n = players.length;
        if (n === 0) return;

        container.innerHTML = '';

        // 计算每位玩家在椭圆桌面上的位置
        const tableEl = document.getElementById('poker-table');
        const tableRect = tableEl.getBoundingClientRect();
        const cx = tableRect.width / 2;
        const cy = tableRect.height / 2;
        const rx = tableRect.width / 2 - 50;
        const ry = tableRect.height / 2 - 80;

        // 按座位号映射到椭圆上的角度
        players.forEach((p, idx) => {
            // 人类玩家 (seat 0) 放在底部中央
            const totalSeats = Math.max(n, 2);

            // 角度分布：seat 0 = 底部，顺时针
            const angle = (p.seat / totalSeats) * 2 * Math.PI - Math.PI / 2;

            const x = cx + rx * Math.cos(angle);
            let y = cy + ry * Math.sin(angle);

            // 顶部/底部的玩家位置向内额外收缩，避免手牌超出桌面边缘
            const threshold = Math.PI * 0.95 / 2; // ~85.5°
            if (angle > Math.PI / 2 - threshold && angle < Math.PI / 2 + threshold) {
                y -= 50; // 底部玩家上移
            } else if (angle < -Math.PI / 2 + threshold && angle > -Math.PI / 2 - threshold) {
                y += 15; // 顶部玩家微调下移
            }

            const spot = document.createElement('div');
            spot.className = 'player-spot';
            spot.style.left = x + 'px';
            spot.style.top = y + 'px';

            const isHuman = p.is_human;
            const isCurrentPlayer = state.current_player_index === p.seat;
            const isFolded = p.status === 'FOLDED';
            const isActive = p.status === 'ACTIVE' || p.status === 'ALL_IN';

            if (isCurrentPlayer && isActive) spot.classList.add('active-turn');
            if (isFolded) spot.classList.add('folded');
            if (p._replay_highlight) spot.classList.add('replay-highlight');

            // 玩家信息卡片
            let blindBadge = '';
            if (p.is_small_blind) blindBadge += '<span class="blind-badge sb-badge">SB</span>';
            if (p.is_big_blind) blindBadge += '<span class="blind-badge bb-badge">BB</span>';

            let dealerBtn = p.is_dealer ? '<span class="dealer-btn">D</span>' : '';

            // 动作标记
            let actionMark = '';
            if (state.phase !== 'WAITING' && state.phase !== 'FINISHED') {
                if (isFolded) actionMark = ' (弃牌)';
                else if (p.status === 'ALL_IN') actionMark = ' (全下!)';
            }

            // 本手下注显示
            let betDisplay = '';
            if (p.current_bet > 0 && state.phase !== 'WAITING') {
                betDisplay = `<div class="player-bet">下注: $${p.current_bet}</div>`;
            }

            // 重购次数显示
            let rebuyDisplay = '';
            if (p.rebuy_count > 0) {
                rebuyDisplay = `<div class="player-rebuy">重购: ${p.rebuy_count}</div>`;
            }

            spot.innerHTML = `
                <div class="player-info ${isHuman ? 'human-player' : ''}">
                    <div class="player-name">${dealerBtn} ${p.name} ${blindBadge} ${actionMark}</div>
                    <div class="player-chips">💰 $${p.chips}</div>
                    ${rebuyDisplay}
                    ${betDisplay}
                    <div class="hole-cards-mini">
                        ${(p.hole_cards || []).map(c => {
                            const path = this._cardImgPath(c);
                            if (!path) return `<div class="hole-card-mini hole-card-back"><img src="${DeckSkin.backPath()}" class="card-img" alt="?"></div>`;
                            return `<div class="hole-card-mini"><img src="${path}" class="card-img" alt="${c}"></div>`;
                        }).join('')}
                    </div>
                </div>
            `;

            container.appendChild(spot);
        });
    },
};
