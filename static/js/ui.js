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

        // 听牌信息
        this._updateDrawInfo(state, humanPlayer);
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

    _updateDrawInfo(state, player) {
        // 简单的听牌检测（前端版）
        const community = (state.community_cards || []).filter(c => c !== '??');
        const hole = (player.hole_cards || []).filter(c => c !== '??');
        const all = [...hole, ...community];

        if (community.length < 3) {
            document.getElementById('draw-flush').className = 'draw-inactive';
            document.getElementById('draw-flush').textContent = '同花听牌: 翻牌后可见';
            document.getElementById('draw-straight').className = 'draw-inactive';
            document.getElementById('draw-straight').textContent = '顺子听牌: 翻牌后可见';
            return;
        }

        // 同花检测
        const suits = {};
        all.forEach(c => {
            const s = c[1] || c[0];
            suits[s] = (suits[s] || 0) + 1;
        });
        const flushDraw = Object.values(suits).some(n => n >= 4);
        document.getElementById('draw-flush').textContent =
            '同花听牌: ' + (flushDraw ? '是 ✓' : '否');
        document.getElementById('draw-flush').className = flushDraw ? 'draw-active' : 'draw-inactive';

        // 顺子检测（简化）
        const rankOrder = '23456789TJQKA';
        const rankVals = all.map(c => rankOrder.indexOf(c[0])).filter(v => v >= 0).sort((a,b)=>a-b);
        let straightDraw = false;
        for (let i = 0; i < rankVals.length - 3; i++) {
            if (rankVals[i+3] - rankVals[i] <= 4) {
                straightDraw = true;
                break;
            }
        }
        document.getElementById('draw-straight').textContent =
            '顺子听牌: ' + (straightDraw ? '是 ✓' : '否');
        document.getElementById('draw-straight').className = straightDraw ? 'draw-active' : 'draw-inactive';
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
                    <div class="history-item">
                        <strong>Hand #${h.hand_id}</strong><br>
                        底池: $${h.pot_total}<br>
                        赢家: ${Object.entries(h.winners || {}).map(([n, a]) => `${n} (+$${a})`).join(', ')}<br>
                        <small>${(h.actions || []).slice(-3).join('<br>')}</small>
                    </div>
                `).join('');
            })
            .catch(() => {});
    },

    /** 显示结果弹窗 */
    showResult(message) {
        document.getElementById('result-body').innerHTML = `<p>${message}</p>`;
        document.getElementById('modal-result').style.display = 'flex';
    },
};

// 初始化标签页
document.addEventListener('DOMContentLoaded', () => UI.init());

// 定期刷新历史
setInterval(() => UI.updateHistory(), 5000);
