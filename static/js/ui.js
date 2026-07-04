/**
 * ui.js — 侧面板管理：战局分析、历史、统计、弹窗。
 */

const UI = {
    /** 初始化标签页切换 */
    init() {
        document.querySelectorAll('.tab-btn').forEach(btn => {
            btn.addEventListener('click', () => {
                document.querySelectorAll('.tab-btn').forEach(b => b.classList.remove('active'));
                document.querySelectorAll('.tab-content').forEach(c => c.classList.remove('active'));
                btn.classList.add('active');
                document.getElementById('panel-' + btn.dataset.tab).classList.add('active');
            });
        });

        // 历史条目点击事件委托 —— 点击进入该局回放
        const historyList = document.getElementById('history-list');
        if (historyList) {
            historyList.addEventListener('click', (e) => {
                const item = e.target.closest('.history-item');
                if (!item) return;
                const handId = parseInt(item.dataset.handId);
                if (handId && window.App) {
                    App._openReplay(handId);
                }
            });
        }
    },

    /** 更新战局分析面板 */
    updateAnalysis(state) {
        if (!state) return;

        const humanPlayer = (state.players || []).find(p => p.is_human);
        if (!humanPlayer || !humanPlayer.hole_cards || humanPlayer.hole_cards[0] === '??') {
            return;
        }

        // 手牌强度可视化
        this._updateHandStrength(state, humanPlayer);

        // 底池赔率
        this._updatePotOdds(state, humanPlayer);

        // 牌型概率
        this._updateHandTypeProbs(state, humanPlayer);
    },

    _updateHandStrength(state, player) {
        const holeCards = player.hole_cards || [];
        const communityCards = state.community_cards || [];
        const allKnown = holeCards.filter(c => c !== '??').concat(
            communityCards.filter(c => c !== '??')
        );

        // 估算强度（基于已知牌）
        let strength = 0;
        if (holeCards.length === 2 && holeCards[0] !== '??') {
            // 仅翻牌前
            const ranks = '23456789TJQKA';
            const r1 = ranks.indexOf(holeCards[0][0]);
            const r2 = ranks.indexOf(holeCards[1][0]);
            if (r1 >= 0 && r2 >= 0) {
                const suited = holeCards[0][1] === holeCards[1][1];
                const isPair = r1 === r2;
                const high = Math.max(r1, r2);
                const low = Math.min(r1, r2);
                if (isPair) strength = 0.5 + (high / 13) * 0.5;
                else if (suited) strength = 0.2 + (high / 13) * 0.3 + (low / 13) * 0.1;
                else strength = 0.1 + (high / 13) * 0.25 + (low / 13) * 0.05;
            }
        }
        if (allKnown.length >= 5) {
            // 翻牌后有 5+ 张已知牌
            const validCards = allKnown.slice(0, 7).length;
            strength = Math.min(1.0, validCards / 7 * 0.8 + 0.1);
        }

        const pct = Math.round(strength * 100);
        document.getElementById('hand-strength-fill').style.width = pct + '%';
        document.getElementById('hand-strength-label').textContent =
            `估算强度: ${pct}%`;
    },

    _updatePotOdds(state, player) {
        const toCall = state.to_call || (state.current_bet - (player.current_bet || 0));
        const pot = state.pot_total || 0;

        document.getElementById('ao-pot').textContent = '$' + pot;
        document.getElementById('ao-to-call').textContent = '$' + Math.max(0, toCall);
        if (toCall > 0) {
            const ratio = (pot + toCall) / toCall;
            const required = (toCall / (pot + toCall)) * 100;
            document.getElementById('ao-ratio').textContent = ratio.toFixed(1) + ':1';
            document.getElementById('ao-required').textContent = required.toFixed(1) + '%';
        } else {
            document.getElementById('ao-ratio').textContent = '--';
            document.getElementById('ao-required').textContent = '0%';
        }
    },

    _updateHandTypeProbs(state, player) {
        const probs = state.hand_type_probs;
        const container = document.getElementById('hand-type-probs');
        const phaseLabel = document.getElementById('draw-phase-label');

        if (!probs || Object.keys(probs).length === 0) {
            container.innerHTML = '<span class="draw-inactive">等待数据...</span>';
            if (phaseLabel) phaseLabel.textContent = '';
            return;
        }

        // 显示当前阶段标签
        const community = (state.community_cards || []).filter(c => c !== '??');
        const phaseNames = {0: '翻牌前', 1: '翻牌前', 2: '翻牌', 3: '转牌', 4: '河牌'};
        const phaseVal = state.phase === 'PRE_FLOP' ? 1
                       : state.phase === 'FLOP' ? 2
                       : state.phase === 'TURN' ? 3
                       : state.phase === 'RIVER' ? 4
                       : state.phase === 'SHOWDOWN' ? 4 : 0;
        if (phaseLabel) {
            phaseLabel.textContent = '· ' + (phaseNames[phaseVal] || '');
        }

        // 牌型显示顺序（从强到弱）
        const orderedKeys = [
            '皇家同花顺', '同花顺', '四条', '葫芦', '同花',
            '顺子', '三条', '两对', '一对', '高牌'
        ];

        // 按 order 排列 probs
        const entries = orderedKeys
            .filter(k => k in probs)
            .map(k => [k, probs[k]]);

        container.innerHTML = entries.map(([name, pct]) => {
            const barClass = pct >= 50 ? 'htp-prob-high'
                           : pct >= 20 ? 'htp-prob-mid'
                           : pct > 0 ? 'htp-prob-low'
                           : 'htp-prob-zero';
            const pctClass = pct > 0 ? 'htp-pct-positive' : 'htp-pct-zero';
            return `<div class="htp-row">
                <span class="htp-label">${name}</span>
                <div class="htp-bar-container">
                    <div class="htp-bar-fill ${barClass}" style="width:${pct}%"></div>
                </div>
                <span class="htp-pct ${pctClass}">${pct.toFixed(1)}%</span>
            </div>`;
        }).join('');
    },

    /** 更新统计面板 */
    updateStats() {
        fetch('/api/game/analysis')
            .then(r => r.json())
            .then(data => {
                if (data.error) return;
                const tbody = document.getElementById('stats-body');
                const stats = data.player_stats || [];
                tbody.innerHTML = stats.map(s => `
                    <tr>
                        <td>${s.name}</td>
                        <td>${(s.vpip * 100).toFixed(0)}%</td>
                        <td>${(s.pfr * 100).toFixed(0)}%</td>
                        <td>${s.aggression_factor.toFixed(1)}</td>
                        <td>${(s.win_rate * 100).toFixed(0)}%</td>
                        <td style="color:${s.profit >= 0 ? '#2ecc71' : '#e74c3c'}">$${s.profit}</td>
                    </tr>
                `).join('');
            })
            .catch(() => {});
    },

    /** 更新历史面板 */
    updateHistory() {
        fetch('/api/game/history')
            .then(r => r.json())
            .then(data => {
                if (data.error) return;
                const list = document.getElementById('history-list');
                const items = Array.isArray(data) ? data : [];
                list.innerHTML = items.map(h => `
                    <div class="history-item" data-hand-id="${h.hand_id}">
                        <div class="history-item-header">
                            <strong>Hand #${h.hand_id}</strong>
                            <span class="history-item-replay">▶ 回放</span>
                        </div>
                        底池: $${h.pot_total}<br>
                        赢家: ${Object.entries(h.winners || {}).map(([n, a]) => `${n} (+$${a})`).join(', ')}<br>
                        <small>${(h.actions || []).slice(-3).join('<br>')}</small>
                    </div>
                `).join('');
                // 重新渲染后恢复当前回放条目的高亮
                if (window.App && App._replayActive && App._replayData) {
                    App._highlightHistoryItem(App._replayData.hand_id);
                }
            })
            .catch(() => {});
    },

    /** 显示结果弹窗（纯文本，用于 game_over 等场景） */
    showResult(message) {
        const body = document.getElementById('result-body');
        body.innerHTML = '';  // 清空
        const p = document.createElement('p');
        p.textContent = message;
        p.style.whiteSpace = 'pre-line';
        body.appendChild(p);
        document.getElementById('modal-result').style.display = 'flex';
    },

    /** 以牌阵形式展示手牌结果（hand_completed） */
    showCardResult(data) {
        const body = document.getElementById('result-body');
        body.innerHTML = '';
        document.getElementById('result-title').textContent =
            `🏆 手牌结果 · Hand #${data.hand_id}`;

        const players = data.players || [];
        if (players.length === 0) return;

        const container = document.createElement('div');
        container.className = 'result-players';

        players.forEach(p => {
            const row = document.createElement('div');
            row.className = 'result-player-row';
            if (p.is_winner) row.classList.add('result-player-winner');
            if (p.is_folded) row.classList.add('result-player-folded');

            // --- 玩家名称 ---
            const nameEl = document.createElement('div');
            nameEl.className = 'result-player-name';
            let nameText = p.name;
            if (p.is_winner) nameText = '🏅 ' + nameText;
            if (p.is_folded) nameText += ' (弃牌)';
            nameEl.textContent = nameText;
            row.appendChild(nameEl);

            // --- 最佳 5 张牌 ---
            const cards = p.best_five || [];
            if (cards.length > 0) {
                const sorted = [...cards].sort((a, b) => {
                    const av = this._cardRankValue(a[0]);
                    const bv = this._cardRankValue(b[0]);
                    return bv - av;
                });
                const cardRow = document.createElement('div');
                cardRow.className = 'result-cards-row';
                sorted.forEach(cs => cardRow.appendChild(this._createCardEl(cs)));
                row.appendChild(cardRow);
            }

            // --- 牌型描述（中列） ---
            const descEl = document.createElement('div');
            descEl.className = 'result-player-desc';
            descEl.textContent = p.hand_description || '—';
            row.appendChild(descEl);

            // --- 盈亏金额（右侧） ---
            const amountEl = document.createElement('div');
            amountEl.className = 'result-player-amount';
            const net = p.net_profit;
            if (net > 0) {
                amountEl.textContent = `+$${net}`;
            } else if (net < 0) {
                amountEl.textContent = `-$${Math.abs(net)}`;
                amountEl.style.color = '#e74c3c';
            } else {
                amountEl.textContent = '$0';
            }
            row.appendChild(amountEl);

            container.appendChild(row);
        });

        body.appendChild(container);

        // --- 底池 ---
        const potLine = document.createElement('div');
        potLine.className = 'result-pot-line';
        potLine.textContent = `底池总额: $${data.pot_total || 0}`;
        body.appendChild(potLine);

        document.getElementById('modal-result').style.display = 'flex';
    },

    /** 点数 → 数值 */
    _cardRankValue(ch) {
        const map = {'A':14,'K':13,'Q':12,'J':11,'T':10};
        return map[ch] || parseInt(ch) || 0;
    },

    /** 创建单张扑克牌 DOM 元素 */
    _createCardEl(cardStr) {
        const el = document.createElement('div');
        el.className = 'card-mini';
        const path = Table._cardImgPath(cardStr);
        if (path) {
            el.innerHTML = `<img src="${path}" class="card-img" alt="${cardStr}">`;
        } else {
            el.innerHTML = `<img src="/static/img/cards/aguilar/back.png" class="card-img" alt="?">`;
        }
        return el;
    },
};

// 初始化标签页
document.addEventListener('DOMContentLoaded', () => UI.init());

// 定期刷新历史
setInterval(() => UI.updateHistory(), 5000);
