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
            Table.render(state);
            Controls.update(state);
            UI.updateAnalysis(state);
            UI.updateStats();

            document.getElementById('hand-counter').textContent =
                `手牌 #${state.hand_id}`;
        });

        this.socket.on('action_required', (data) => {
            Controls.setStatus('轮到你行动了！');
        });

        this.socket.on('game_over', (data) => {
            Controls.setStatus('游戏结束');
            Controls.disableAll();
            UI.showResult(data.message || '游戏结束！');
        });
    },

    /** 绑定 UI 事件 */
    _bindUIEvents() {
        // 对手数量变化 → 刷新机器人列表
        document.getElementById('input-bot-count').addEventListener('change', () => {
            this._refreshBotRows();
        });

        // 新游戏按钮
        document.getElementById('btn-new-game').addEventListener('click', () => {
            this._refreshBotRows();  // 确保显示当前数量的机器人
            document.getElementById('modal-new-game').style.display = 'flex';
        });

        // 设置按钮
        document.getElementById('btn-settings').addEventListener('click', () => {
            this._refreshBotRows();
            document.getElementById('modal-new-game').style.display = 'flex';
        });

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
        document.getElementById('btn-close-replay').addEventListener('click', () => {
            this._pauseReplay();
            document.getElementById('modal-replay').style.display = 'none';
        });
        document.getElementById('btn-replay-from-result').addEventListener('click', () => {
            document.getElementById('modal-result').style.display = 'none';
            this._openReplay();
        });

        // 回放控制
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

    // ============ 回放系统 ============

    _replayData: null,
    _replayStep: 0,
    _replayPlaying: false,
    _replayTimer: null,

    /** 打开回放面板 */
    _openReplay() {
        fetch('/api/game/replay')
            .then(r => r.json())
            .then(data => {
                if (data.error) { alert(data.error); return; }
                this._replayData = data;
                this._replayStep = 0;
                this._replayPlaying = false;
                document.getElementById('replay-hand-id').textContent = `#${data.hand_id}`;

                // 显示玩家底牌
                const playersDiv = document.getElementById('replay-players');
                playersDiv.innerHTML = data.players.map(p =>
                    `<div class="rp-player">
                        ${p.is_human ? '👤' : '🤖'} <b>${p.name}</b>
                        <span class="rp-cards">${(p.hole_cards || []).join(' ')}</span>
                    </div>`
                ).join('');

                this._renderReplay();
                document.getElementById('modal-replay').style.display = 'flex';
            })
            .catch(e => alert('获取回放数据失败: ' + e));
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
        if (!this._replayPlaying) return;
        if (this._replayStep < (this._replayData?.actions?.length || 0)) {
            this._renderReplay();
            this._replayStep++;
            this._replayTimer = setTimeout(() => this._replayAdvance(), 1000);
        } else {
            this._pauseReplay();
        }
    },

    /** 手动步进 */
    _stepReplay(delta) {
        this._pauseReplay();
        const max = this._replayData?.actions?.length || 0;
        this._replayStep = Math.max(0, Math.min(max, this._replayStep + delta));
        this._renderReplay();
    },

    /** 重置回放 */
    _resetReplay() {
        this._pauseReplay();
        this._replayStep = 0;
        this._renderReplay();
    },

    /** 渲染回放状态 */
    _renderReplay() {
        const data = this._replayData;
        if (!data) return;

        const actions = data.actions || [];
        const max = actions.length;

        // 渲染时间轴
        const timeline = document.getElementById('replay-timeline');
        timeline.innerHTML = actions.map((a, i) => {
            let cls = 'rp-step';
            if (i < this._replayStep) cls += ' past';
            if (i === this._replayStep && this._replayStep < max) cls += ' current';
            const actionLabel = this._formatAction(a);
            return `<div class="${cls}" onclick="App._jumpReplay(${i})">
                <span class="rp-step-num">#${i + 1}</span>
                <span>${actionLabel}</span>
            </div>`;
        }).join('');

        // 滚动到当前步骤
        const currentEl = timeline.querySelector('.rp-step.current');
        if (currentEl) currentEl.scrollIntoView({ block: 'nearest', behavior: 'smooth' });

        // 更新步骤计数器
        document.getElementById('replay-step-counter').textContent =
            `${Math.min(this._replayStep, max)} / ${max}`;

        // 显示当前动作详情
        const infoDiv = document.getElementById('replay-action-info');
        if (this._replayStep < max) {
            const a = actions[this._replayStep];
            infoDiv.innerHTML = `<span class="rp-action-player">${a.player}</span>
                → <span class="rp-action-type">${this._formatAction(a)}</span>`;
        } else {
            // 回放结束，显示结果
            const winners = data.winners || {};
            const hands = data.winning_hands || {};
            const winnerText = Object.entries(winners)
                .map(([n, amt]) => `${n} +$${amt}${hands[n] ? ' (' + hands[n] + ')' : ''}`)
                .join(', ');
            infoDiv.innerHTML = `🏆 本局结束 — 公共牌: <b>${(data.community_cards || []).join(' ')}</b> — 赢家: ${winnerText}`;
        }

        // 更新按钮状态
        document.getElementById('btn-replay-prev').disabled = this._replayStep <= 0;
        document.getElementById('btn-replay-next').disabled = this._replayStep >= max;
        document.getElementById('btn-replay-play').disabled = this._replayStep >= max;
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

    /** 跳转到指定步骤（从 HTML onclick 调用） */
    _jumpReplay(step) {
        this._pauseReplay();
        this._replayStep = step;
        this._renderReplay();
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
