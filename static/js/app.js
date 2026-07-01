/**
 * app.js — 主入口：SocketIO 连接、状态管理、事件路由。
 */

const App = {
    socket: null,
    gameState: null,
    connected: false,

    /** 初始化 */
    init() {
        this.socket = io();
        this._bindSocketEvents();
        this._bindUIEvents();
        console.log('[App] 初始化完成');
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
        // 新游戏按钮
        document.getElementById('btn-new-game').addEventListener('click', () => {
            document.getElementById('modal-new-game').style.display = 'flex';
        });

        // 设置按钮
        document.getElementById('btn-settings').addEventListener('click', () => {
            // 简化：直接打开新游戏弹窗
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

        // 动作按钮
        Controls.bindEvents(this);
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
