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
                const handId = parseInt(item.dataset.handId, 10);
                if (!Number.isNaN(handId) && typeof App !== 'undefined') {
                    App._openReplay(handId);
                }
            });
        }

        // Tooltip 系统：JS 驱动，支持 HTML 内容 + fixed 定位防遮挡
        this._initTooltips();
    },

    /** 初始化 info-icon hover tooltip */
    _initTooltips() {
        const tipEl = document.createElement('div');
        tipEl.className = 'tooltip-popup';
        tipEl.id = 'global-tooltip';
        document.body.appendChild(tipEl);

        let showTimer = null;

        document.addEventListener('mouseenter', (e) => {
            const icon = e.target.closest('.info-icon');
            if (!icon) return;
            const html = icon.getAttribute('data-tip') || '';
            tipEl.innerHTML = html;
            showTimer = setTimeout(() => {
                this._positionTooltip(tipEl, icon);
                tipEl.classList.add('show');
            }, 200);
        }, true);

        document.addEventListener('mouseleave', (e) => {
            const icon = e.target.closest('.info-icon');
            if (!icon) return;
            clearTimeout(showTimer);
            tipEl.classList.remove('show');
        }, true);
    },

    /** 将 tooltip 定位在图标上方 */
    _positionTooltip(tipEl, icon) {
        const rect = icon.getBoundingClientRect();
        const gap = 8;
        // 默认放在图标上方
        let top = rect.top - tipEl.offsetHeight - gap;
        let left = rect.left + rect.width / 2 - tipEl.offsetWidth / 2;

        // 如果上方空间不够，放到下方
        if (top < 4) {
            top = rect.bottom + gap;
        }
        // 避免超出左边界
        if (left < 4) left = 4;
        // 避免超出右边界
        const maxLeft = window.innerWidth - tipEl.offsetWidth - 4;
        if (left > maxLeft) left = maxLeft;

        tipEl.style.top = top + 'px';
        tipEl.style.left = left + 'px';
    },

    /** 更新战局分析面板 */
    updateAnalysis(state) {
        if (!state) return;

        const humanPlayer = (state.players || []).find(p => p.is_human);
        if (!humanPlayer || !humanPlayer.hole_cards || humanPlayer.hole_cards[0] === '??') {
            return;
        }

        // 区域1: 牌型概率
        this._renderHandTypeProbs(state);

        // 区域2: 排名分布律
        this._renderRankingDistribution(state);

        // 区域3: 赔率与期望值
        this._renderOddsEv(state);

        // 区域4: 底池详情
        this._renderPotFinancials(state);
    },

    /** 区域1: 牌型概率 — 柱状图 */
    _renderHandTypeProbs(state) {
        const probs = state.hand_type_probs;
        const container = document.getElementById('hand-type-probs');
        const phaseLabel = document.getElementById('draw-phase-label');

        if (!probs || Object.keys(probs).length === 0) {
            if (container) container.innerHTML = '<span class="draw-inactive">等待数据...</span>';
            if (phaseLabel) phaseLabel.textContent = '';
            return;
        }

        // 阶段标签
        const phaseNames = {'PRE_FLOP':'翻牌前','FLOP':'翻牌','TURN':'转牌','RIVER':'河牌','SHOWDOWN':'河牌'};
        if (phaseLabel) phaseLabel.textContent = '· ' + (phaseNames[state.phase] || '');

        // 牌型显示顺序（从强到弱）
        const orderedKeys = [
            '皇家同花顺', '同花顺', '四条', '葫芦', '同花',
            '顺子', '三条', '两对', '一对', '高牌'
        ];

        const entries = orderedKeys.filter(k => k in probs).map(k => [k, probs[k]]);

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

    /** 区域2: 排名分布律 — 柱状图 */
    _renderRankingDistribution(state) {
        const dist = state.ranking_distribution;
        const container = document.getElementById('ranking-distribution');
        if (!container) return;

        if (!dist || dist.length === 0) {
            container.innerHTML = '<span class="draw-inactive">等待数据...</span>';
            return;
        }

        container.innerHTML = dist.map(entry => {
            const isWin = entry.rank === 1;
            const rowClass = isWin ? 'rnk-row win-row' : 'rnk-row';
            const barWidth = Math.max(entry.prob, isWin ? 1 : 0);
            return `<div class="${rowClass}">
                <span class="rnk-label">${entry.desc}</span>
                <div class="rnk-bar-container">
                    <div class="rnk-bar-fill" style="width:${barWidth}%"></div>
                </div>
                <span class="rnk-pct">${entry.prob.toFixed(1)}%</span>
            </div>`;
        }).join('');
    },

    /** 区域3: 赔率与期望值 — 数据行 */
    _renderOddsEv(state) {
        const data = state.odds_ev;
        const container = document.getElementById('odds-ev-display');
        if (!container) return;

        if (!data) {
            container.innerHTML = '<span class="draw-inactive">等待数据...</span>';
            return;
        }

        const hasCall = data.has_call_decision;
        const evClass = hasCall ? (data.ev >= 0 ? 'positive' : 'negative') : 'neutral';
        const rows = [
            { label: '胜率', value: data.win_rate + '%' },
            { label: '底池赔率', value: data.pot_odds_ratio > 0 ? data.pot_odds_ratio + ':1' : '--' },
            { label: '所需胜率', value: data.required_equity.toFixed(1) + '%' },
        ];

        const evLabel = hasCall ? '期望值 EV' : '底池权益';
        const judgmentHtml = hasCall
            ? `<div class="metric-row metric-judgment">${data.ev_judgment}</div>`
            : '';

        container.innerHTML =
            rows.map(r =>
                `<div class="metric-row">
                    <span class="metric-label">${r.label}</span>
                    <span class="metric-value neutral">${r.value}</span>
                </div>`
            ).join('') +
            judgmentHtml +
            `<div class="metric-row">
                <span class="metric-label">${evLabel}
                    <span class="info-icon" data-tip="${hasCall
                        ? 'EV = P(win) &times; 底池 - P(lose) &times; 跟注额<br><br>EV &gt; 0 表示长期有利，EV &lt; 0 表示长期亏损。'
                        : '底池权益 = P(win) &times; 底池总额<br><br>无需跟注时不存在 EV 决策，此值表示你当前在底池中的期望份额（若立即摊牌）。'}">?</span>
                </span>
                <span class="metric-value ${evClass}">${hasCall ? (data.ev >= 0 ? '+' : '') + '$' + data.ev : '$' + data.ev}</span>
            </div>`;
    },

    /** 区域4: 底池详情 — 数据行 */
    _renderPotFinancials(state) {
        const data = state.pot_financials;
        const container = document.getElementById('pot-financials');
        if (!container) return;

        if (!data) {
            container.innerHTML = '<span class="draw-inactive">等待数据...</span>';
            return;
        }

        container.innerHTML = [
            { label: '底池总额', value: '$' + data.pot_total, cls: 'metric-amount' },
            { label: '死钱', value: '$' + data.dead_money, cls: 'neutral' },
            { label: '沉没成本', value: '$' + data.sunk_cost, cls: 'neutral' },
            { label: '跟注金额', value: data.to_call > 0 ? '$' + data.to_call : '免费', cls: 'neutral' },
        ].map(r =>
            `<div class="metric-row">
                <span class="metric-label">${r.label}</span>
                <span class="metric-value ${r.cls}">${r.value}</span>
            </div>`
        ).join('');
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
                        <td>${((s.vpip ?? 0) * 100).toFixed(0)}%</td>
                        <td>${((s.pfr ?? 0) * 100).toFixed(0)}%</td>
                        <td>${(s.aggression_factor ?? 0).toFixed(1)}</td>
                        <td>${((s.win_rate ?? 0) * 100).toFixed(0)}%</td>
                        <td style="color:${(s.profit ?? 0) >= 0 ? '#2ecc71' : '#e74c3c'}">$${s.profit ?? 0}</td>
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
                if (typeof App !== 'undefined' && App._replayActive && App._replayData) {
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
                const holeCards = p.hole_cards || [];
                const cardRow = document.createElement('div');
                cardRow.className = 'result-cards-row';
                sorted.forEach(cs => {
                    const el = this._createCardEl(cs);
                    if (holeCards.includes(cs)) {
                        el.classList.add('card-hole-personal');
                    }
                    cardRow.appendChild(el);
                });
                row.appendChild(cardRow);
            }

            // --- 牌型描述（中列） ---
            const descEl = document.createElement('div');
            descEl.className = 'result-player-desc';
            descEl.textContent = p.hand_description || (p.is_folded ? '弃牌' : '—');
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
        const path = DeckSkin.cardPath(cardStr);
        if (path) {
            el.innerHTML = `<img src="${path}" class="card-img" alt="${cardStr}">`;
        } else {
            el.innerHTML = `<img src="${DeckSkin.backPath()}" class="card-img" alt="?">`;
        }
        return el;
    },
};

// 初始化标签页
document.addEventListener('DOMContentLoaded', () => UI.init());

// 定期刷新历史
setInterval(() => UI.updateHistory(), 5000);
