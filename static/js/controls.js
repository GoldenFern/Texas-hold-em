/**
 * controls.js — 动作面板：Fold/Check/Call/Raise 按钮及下注控制。
 */

const Controls = {
    _app: null,
    _currentBetAction: 'raise',
    _betControlsVisible: false,

    /** 绑定动作按钮事件 */
    bindEvents(app) {
        this._app = app;

        document.getElementById('btn-fold').addEventListener('click', () => {
            app.sendAction('fold');
        });
        document.getElementById('btn-check').addEventListener('click', () => {
            app.sendAction('check');
        });
        document.getElementById('btn-call').addEventListener('click', () => {
            app.sendAction('call');
        });
        document.getElementById('btn-raise').addEventListener('click', () => {
            // 新下注轮用 BET，已有下注时用 RAISE
            const legalActions = app.gameState?.legal_actions || [];
            const action = legalActions.includes('BET') ? 'bet' : 'raise';
            this._showBetControls(action);
        });
        document.getElementById('btn-bet-confirm').addEventListener('click', () => {
            const amount = parseInt(document.getElementById('bet-amount').value) || 0;
            const action = this._currentBetAction || 'raise';
            app.sendAction(action, amount);
            this._hideBetControls();
        });

        // 滑块联动
        document.getElementById('bet-slider').addEventListener('input', (e) => {
            document.getElementById('bet-amount').value = e.target.value;
        });
        document.getElementById('bet-amount').addEventListener('input', (e) => {
            document.getElementById('bet-slider').value = e.target.value;
        });
    },

    _showBetControls(action) {
        this._currentBetAction = action;
        this._betControlsVisible = true;
        document.getElementById('action-buttons').style.display = 'none';
        document.getElementById('bet-controls').style.display = 'flex';
        document.getElementById('btn-bet-confirm').textContent =
            action === 'bet' ? '下注' : '加注';
    },

    _hideBetControls() {
        this._betControlsVisible = false;
        document.getElementById('action-buttons').style.display = 'flex';
        document.getElementById('bet-controls').style.display = 'none';
    },

    /** 根据 gameState 更新动作按钮 */
    update(state) {
        const legalActions = state.legal_actions || [];
        const toCall = state.to_call || 0;
        const minRaise = state.min_raise || 0;
        const maxBet = state.max_bet || 0;
        const humanPlayer = (state.players || []).find(p => p.is_human);

        if (!humanPlayer || legalActions.length === 0) {
            this.disableAll();
            this.setStatus('等待中...');
            return;
        }

        // 更新状态文字
        const phaseNames = {
            'PRE_FLOP': '翻牌前', 'FLOP': '翻牌', 'TURN': '转牌', 'RIVER': '河牌'
        };
        const phaseName = phaseNames[state.phase] || state.phase;
        if (toCall > 0) {
            this.setStatus(`轮到你行动 (${phaseName})`);
            document.getElementById('action-to-call').textContent =
                `需要跟注: $${toCall}`;
        } else {
            this.setStatus(`轮到你行动 (${phaseName}) - 免费看牌`);
            document.getElementById('action-to-call').textContent = '';
        }

        // 启用/禁用按钮
        const hasAction = (a) => legalActions.includes(a);

        document.getElementById('btn-fold').disabled = !hasAction('FOLD');
        document.getElementById('btn-check').disabled = !hasAction('CHECK');
        document.getElementById('btn-call').disabled = !hasAction('CALL');
        document.getElementById('btn-raise').disabled = !hasAction('RAISE') && !hasAction('BET');

        // 更新 Call 按钮文字
        if (toCall > 0) {
            document.getElementById('btn-call').textContent = `Call $${toCall}`;
        } else {
            document.getElementById('btn-call').textContent = 'Call';
            document.getElementById('btn-call').disabled = true;
        }

        // 更新 Bet/Raise 按钮文字
        const canRaise = hasAction('RAISE');
        const canBet = hasAction('BET');
        if (canBet || canRaise) {
            const btn = document.getElementById('btn-raise');
            btn.textContent = canBet ? 'Bet' : 'Raise';
            btn.disabled = false;
        }

        // 更新下注滑块
        if (canBet || canRaise) {
            const slider = document.getElementById('bet-slider');
            slider.min = minRaise;
            slider.max = maxBet;
            slider.value = minRaise;
            document.getElementById('bet-amount').min = minRaise;
            document.getElementById('bet-amount').max = maxBet;
            document.getElementById('bet-amount').value = minRaise;
        }
    },

    /** 禁用所有动作按钮 */
    disableAll() {
        ['fold', 'check', 'call', 'raise'].forEach(id => {
            document.getElementById('btn-' + id).disabled = true;
        });
    },

    /** 设置状态文本 */
    setStatus(text) {
        document.getElementById('action-status').textContent = text;
    },

    /** 手牌完成后显示结果和继续/结束按钮 */
    showHandResult(data) {
        const winners = data.winners || {};
        const hands = data.winning_hands || {};
        const winnerText = Object.entries(winners)
            .map(([n, amt]) => `${n} +$${amt}${hands[n] ? ' (' + hands[n] + ')' : ''}`)
            .join(', ');

        console.log('[Controls] 手牌完成:', data.hand_id, winnerText);
        this.setStatus(`🏆 手牌 #${data.hand_id} 结束 — 赢家: ${winnerText}`);

        // 隐藏常规动作按钮，显示继续/结束按钮
        document.getElementById('action-buttons').style.display = 'none';
        document.getElementById('bet-controls').style.display = 'none';

        let pauseDiv = document.getElementById('hand-pause-controls');
        if (!pauseDiv) {
            pauseDiv = document.createElement('div');
            pauseDiv.id = 'hand-pause-controls';
            pauseDiv.style.cssText = 'display:flex;gap:10px;justify-content:center;';
            pauseDiv.innerHTML = `
                <button id="btn-continue-game" class="btn btn-action btn-primary">▶ 继续下一局</button>
                <button id="btn-end-game" class="btn btn-action btn-danger">⏹ 结束游戏</button>
            `;
            document.getElementById('action-panel').appendChild(pauseDiv);

            // 事件委托给 App
            document.getElementById('btn-continue-game').addEventListener('click', () => {
                this._app.socket.emit('continue_game');
            });
            document.getElementById('btn-end-game').addEventListener('click', () => {
                this._app.socket.emit('end_game');
            });
        }
        pauseDiv.style.display = 'flex';
    },

    /** 隐藏暂停按钮，恢复常规动作按钮 */
    hideHandResult() {
        const pauseDiv = document.getElementById('hand-pause-controls');
        if (pauseDiv) pauseDiv.style.display = 'none';
        const actionBtns = document.getElementById('action-buttons');
        if (actionBtns) actionBtns.style.display = '';
    },
};
