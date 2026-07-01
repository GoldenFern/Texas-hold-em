/**
 * app.js — 主入口：SocketIO 连接、状态管理、事件路由。
 */

// 机器人风格列表（value: 英文键, label: 中文成语）
const BOT_STYLES = [
    { value: 'TAG',              label: '老谋深算' },
    { value: 'LAG',              label: '锋芒毕露' },
    { value: 'NIT',              label: '谨小慎微' },
    { value: 'CALLING_STATION',  label: '随波逐流' },
    { value: 'MANIAC',           label: '狂放不羁' },
    { value: 'SHARK',            label: '运筹帷幄' },
    { value: 'LLM',              label: '神机妙算' },
];

// 默认机器人名字
const DEFAULT_BOT_NAMES = ['曹操', '刘备', '孙权', '诸葛', '司马', '周瑜', '吕布', '赵云'];

const App = {
    socket: null,
    gameState: null,
    connected: false,

    /** 初始化 */
    init() {
        this.socket = io();
        this._bindSocketEvents();
        this._bindUIEvents();
        this._refreshBotRows();  // 生成默认 5 个机器人
        console.log('[App] 初始化完成');
    },

    /** 根据对手数量刷新机器人行 */
    _refreshBotRows() {
        const count = parseInt(document.getElementById('input-bot-count').value) || 5;
        const container = document.getElementById('bot-config-list');
        container.innerHTML = '';

        for (let i = 0; i < count; i++) {
            const row = document.createElement('div');
            row.className = 'bot-row';

            // 风格下拉
            const select = document.createElement('select');
            select.className = 'bot-style';
            BOT_STYLES.forEach((s, idx) => {
                const opt = document.createElement('option');
                opt.value = s.value;
                opt.textContent = s.label;
                if (idx === i % BOT_STYLES.length) opt.selected = true;  // 轮流默认风格
                select.appendChild(opt);
            });

            // 名字输入
            const input = document.createElement('input');
            input.type = 'text';
            input.className = 'bot-name';
            input.value = DEFAULT_BOT_NAMES[i] || `Bot${i + 1}`;
            input.maxLength = 12;

            row.appendChild(select);
            row.appendChild(input);
            container.appendChild(row);
        }
    },

    /** 绑定 SocketIO 事件 */
    _bindSocketEvents() {
        this.socket.on('connect', () => {
            this.connected = true;
            console.log('[App] 已连接');
            Controls.setStatus('已连接到服务器，点击"新游戏"开始');
        });

        this.socket.on('disconnect', () => {
            this.connected = false;
            Controls.setStatus('连接断开');
        });

        this.socket.on('game_update', (state) => {
            this.gameState = state;
            Controls.hideHandResult();  // 新状态到达时隐藏暂停面板
            Table.render(state);
            Controls.update(state);
            UI.updateAnalysis(state);
            UI.updateStats();

            // 更新手牌计数器（两处：header 和 toolbar）
            const handText = `手牌 #${state.hand_id}`;
            const hc = document.getElementById('hand-counter');
            if (hc) hc.textContent = handText;
            const hct = document.getElementById('hand-counter-toolbar');
            if (hct) hct.textContent = handText;
        });

        this.socket.on('action_required', (data) => {
            Controls.setStatus('轮到你行动了！');
        });

        this.socket.on('hand_completed', (data) => {
            Controls.showHandResult(data);
            UI.showResult(
                `手牌 #${data.hand_id} 结束\n\n` +
                Object.entries(data.winners || {}).map(([n, amt]) =>
                    `${n} +$${amt}${(data.winning_hands || {})[n] ? ' (' + data.winning_hands[n] + ')' : ''}`
                ).join('\n') +
                `\n\n底池: $${data.pot_total}`
            );
        });

        this.socket.on('game_over', (data) => {
            Controls.setStatus('游戏结束');
            Controls.disableAll();
            Controls.hideHandResult();
            UI.showResult(data.message || '游戏结束！');
        });
    },

    /** 绑定 UI 事件 */
    _bindUIEvents() {
        // 对手数量变化 → 刷新机器人列表
        document.getElementById('input-bot-count').addEventListener('change', () => {
            this._refreshBotRows();
        });

        // 历史回放按钮 — 切换回放模式
        document.getElementById('btn-replay-history').addEventListener('click', () => {
            if (this._replayActive) {
                this._exitReplay();
            } else {
                this._openReplay();
            }
        });

        // 新游戏按钮
        document.getElementById('btn-new-game').addEventListener('click', () => {
            this._refreshBotRows();  // 确保显示当前数量的机器人
            document.getElementById('modal-new-game').style.display = 'flex';
        });

        // 设置按钮 — 由 settings.js 处理

        // 开始游戏
        document.getElementById('btn-start-game').addEventListener('click', () => {
            this._startNewGame();
        });

        // 关闭弹窗
        document.getElementById('btn-close-modal').addEventListener('click', () => {
            document.getElementById('modal-new-game').style.display = 'none';
        });
        document.getElementById('btn-close-result').addEventListener('click', () => {
            document.getElementById('modal-result').style.display = 'none';
        });
        document.getElementById('btn-replay-from-result').addEventListener('click', () => {
            document.getElementById('modal-result').style.display = 'none';
            this._openReplay();
        });

        // 回放控制
        document.getElementById('replay-hand-selector').addEventListener('change', (e) => {
            this._loadReplayHand(parseInt(e.target.value));
        });
        document.getElementById('btn-replay-play').addEventListener('click', () => {
            if (this._replayPlaying) this._pauseReplay();
            else this._startReplay();
        });
        document.getElementById('btn-replay-prev').addEventListener('click', () => this._stepReplay(-1));
        document.getElementById('btn-replay-next').addEventListener('click', () => this._stepReplay(1));
        document.getElementById('btn-replay-reset').addEventListener('click', () => this._resetReplay());

        // 动作按钮
        Controls.bindEvents(this);
    },

    // ============ 回放系统（视觉牌桌回放）============

    _replayData: null,
    _replayStep: 0,
    _replayPlaying: false,
    _replayTimer: null,
    _replayActive: false,      // 是否处于回放模式

    /** 打开回放面板（handId 可选，默认最近一手） */
    _openReplay(handId) {
        fetch('/api/game/replays')
            .then(r => r.json())
            .then(list => {
                if (list.error) { alert(list.error); return; }
                if (!list.length) { alert('还没有任何可回放的手牌'); return; }

                const selector = document.getElementById('replay-hand-selector');
                selector.innerHTML = list.map(h => {
                    const winnerText = Object.entries(h.winners || {})
                        .map(([n, amt]) => `${n} +$${amt}`).join(', ');
                    return `<option value="${h.hand_id}">#${h.hand_id} — ${h.num_actions} 步 — ${winnerText}</option>`;
                }).join('');

                const targetId = handId || list[list.length - 1].hand_id;
                selector.value = targetId;
                this._loadReplayHand(targetId);
            })
            .catch(e => alert('获取回放列表失败: ' + e));
    },

    /** 加载指定手牌的回放数据 */
    _loadReplayHand(handId) {
        fetch(`/api/game/replay?hand_id=${handId}`)
            .then(r => r.json())
            .then(data => {
                if (data.error) { alert(data.error); return; }
                this._replayData = data;
                this._replayStep = 0;
                this._replayPlaying = false;
                this._replayActive = true;
                document.getElementById('btn-replay-play').textContent = '▶ 播放';

                // 隐藏常规 UI，显示回放控件
                Controls.disableAll();
                Controls.setStatus('🔄 回放模式 — 手牌 #' + data.hand_id);
                const overlay = document.getElementById('replay-overlay');
                if (overlay) {
                    overlay.style.display = 'flex';
                    overlay.style.flexDirection = 'column';
                    overlay.style.alignItems = 'center';
                    overlay.style.gap = '6px';
                }
                document.getElementById('hand-counter-toolbar').textContent = `回放 #${data.hand_id}`;
                document.getElementById('btn-replay-history').textContent = '退出回放';

                try {
                    this._renderReplayTable();
                } catch (e) {
                    console.error('渲染回放失败:', e);
                }
            })
            .catch(e => alert('获取回放数据失败: ' + e));
    },

    /** 退出回放 */
    _exitReplay() {
        this._pauseReplay();
        this._replayActive = false;
        const overlay = document.getElementById('replay-overlay');
        if (overlay) overlay.style.display = 'none';
        document.getElementById('btn-replay-history').textContent = '🔄 历史回放';
        document.getElementById('hand-counter-toolbar').textContent = this.gameState ? `手牌 #${this.gameState.hand_id}` : '等待开始';
        Controls.setStatus('');
        // 恢复牌桌
        try {
            if (this.gameState) {
                Table.render(this.gameState);
                Controls.update(this.gameState);
            }
        } catch (e) {
            console.error('恢复牌桌失败:', e);
        }
    },

    /** 构建回放步骤对应的游戏状态并渲染到牌桌 */
    _renderReplayTable() {
        const data = this._replayData;
        if (!data) return;
        const max = (data.actions || []).length;
        const step = Math.min(this._replayStep, max);

        // 确定当前阶段和可见社区牌
        const boundaries = data.phase_boundaries || [0];
        let phaseIdx = 0;
        let visibleCards = [];
        for (let i = boundaries.length - 1; i >= 0; i--) {
            if (step >= boundaries[i]) { phaseIdx = i; break; }
        }
        if (phaseIdx >= 1) visibleCards = data.community_cards.slice(0, 3);
        if (phaseIdx >= 2) visibleCards = data.community_cards.slice(0, 4);
        if (phaseIdx >= 3) visibleCards = data.community_cards.slice(0, 5);
        if (step >= max) visibleCards = data.community_cards;  // 结束时显示全部

        const phaseNames = ['PRE_FLOP', 'FLOP', 'TURN', 'RIVER'];

        // 构建虚假 game state 供 Table.render 使用
        const currentAction = step < max ? data.actions[step] : null;
        const actingPlayer = currentAction ? currentAction.player : null;

        const fakeState = {
            hand_id: data.hand_id,
            phase: step >= max ? 'FINISHED' : (phaseNames[phaseIdx] || 'PRE_FLOP'),
            community_cards: visibleCards,
            pot_total: data.pot_total,
            current_bet: 0,
            dealer_index: -1,
            current_player_index: -1,
            betting_structure: 'no_limit',
            small_blind: 0,
            big_blind: 0,
            ante: 0,
            players: data.players.map(p => ({
                name: p.name,
                chips: 0,  // 回放中不显示精确筹码
                seat: 0,
                status: actingPlayer === p.name ? 'ACTIVE' : 'ACTIVE',
                current_bet: 0,
                total_bet: 0,
                is_dealer: false,
                is_small_blind: false,
                is_big_blind: false,
                is_human: p.is_human,
                hands_won: 0,
                total_won: 0,
                hole_cards: p.hole_cards || [],  // 所有底牌可见
                // 额外的回放标记
                _replay_highlight: actingPlayer === p.name,
            })),
            winners: step >= max ? data.winners : {},
            legal_actions: [],
            _is_replay: true,
        };

        Table.render(fakeState);

        // 更新回放信息栏
        document.getElementById('replay-step-counter').textContent =
            `${Math.min(step, max)} / ${max}`;

        let infoHTML = '';
        if (step < max && currentAction) {
            const actionLabel = this._formatAction(currentAction);
            const phaseLabel = phaseNames[phaseIdx] || '?';
            infoHTML = `<span style="color:var(--gold);">${phaseLabel}</span> →
                <b>${currentAction.player}</b> ${actionLabel}`;
        } else {
            const winners = data.winners || {};
            const hands = data.winning_hands || {};
            const winnerText = Object.entries(winners)
                .map(([n, amt]) => `${n} +$${amt}${hands[n] ? ' (' + hands[n] + ')' : ''}`)
                .join(', ');
            infoHTML = `🏆 公共牌: <b>${(data.community_cards || []).join(' ')}</b> — ${winnerText}`;
        }
        document.getElementById('replay-action-info').textContent = '';
        document.getElementById('replay-action-info').innerHTML = infoHTML;

        // 更新按钮
        document.getElementById('btn-replay-prev').disabled = step <= 0;
        document.getElementById('btn-replay-play').disabled = step >= max;
        document.getElementById('btn-replay-next').disabled = step >= max;
    },

    /** 开始自动播放 */
    _startReplay() {
        this._replayPlaying = true;
        document.getElementById('btn-replay-play').textContent = '⏸ 暂停';
        this._replayAdvance();
    },

    /** 暂停 */
    _pauseReplay() {
        this._replayPlaying = false;
        document.getElementById('btn-replay-play').textContent = '▶ 播放';
        if (this._replayTimer) { clearTimeout(this._replayTimer); this._replayTimer = null; }
    },

    /** 自动推进 */
    _replayAdvance() {
        if (!this._replayPlaying || !this._replayActive) return;
        const max = this._replayData?.actions?.length || 0;
        if (this._replayStep < max) {
            this._renderReplayTable();
            this._replayStep++;
            this._replayTimer = setTimeout(() => this._replayAdvance(), 1200);
        } else {
            this._renderReplayTable();
            this._pauseReplay();
        }
    },

    /** 手动步进 */
    _stepReplay(delta) {
        this._pauseReplay();
        const max = this._replayData?.actions?.length || 0;
        this._replayStep = Math.max(0, Math.min(max, this._replayStep + delta));
        this._renderReplayTable();
    },

    /** 重置回放 */
    _resetReplay() {
        this._pauseReplay();
        this._replayStep = 0;
        this._renderReplayTable();
    },

    /** 格式化动作文本 */
    _formatAction(a) {
        const actionNames = {
            'FOLD': '弃牌', 'CHECK': '过牌', 'CALL': '跟注',
            'BET': '下注', 'RAISE': '加注', 'ALL_IN': '全下'
        };
        const name = actionNames[a.action] || a.action;
        if (a.amount > 0) return `${name} $${a.amount}`;
        return name;
    },

    /** 开始新游戏 */
    _startNewGame() {
        const playerName = document.getElementById('input-player-name').value || 'Hero';
        const startingChips = parseInt(document.getElementById('input-starting-chips').value) || 1000;
        const sb = parseInt(document.getElementById('input-sb').value) || 5;
        const bb = parseInt(document.getElementById('input-bb').value) || 10;
        const bettingStructure = document.getElementById('input-betting-structure').value;

        // 收集机器人配置
        const botRows = document.querySelectorAll('.bot-row');
        const bots = [];
        botRows.forEach(row => {
            const style = row.querySelector('.bot-style').value;
            const name = row.querySelector('.bot-name').value || style;
            bots.push({ style, name });
        });

        document.getElementById('modal-new-game').style.display = 'none';
        Controls.setStatus('正在开始新游戏...');

        this.socket.emit('new_game', {
            player_name: playerName,
            bots,
            starting_chips: startingChips,
            small_blind: sb,
            big_blind: bb,
            betting_structure: bettingStructure,
        });
    },

    /** 发送玩家动作 */
    sendAction(action, amount = 0) {
        this.socket.emit('player_action', { action, amount });
    },
};

// 启动
document.addEventListener('DOMContentLoaded', () => App.init());
