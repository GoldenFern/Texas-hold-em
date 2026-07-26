/**
 * LLM Context 调试面板 —— 在侧边栏显示最近一次 LLM 调用的完整上下文。
 *
 * 数据来源：GET /api/game/llm_context（由 GameManager 和 LLMBot 提供）。
 * 在每次 game_update 后自动刷新。
 */
const ContextDebug = {

    _lastHandId: 0,
    _lastCallIndex: 0,

    /**
     * 获取并渲染 LLM 上下文数据。
     * 在 game_update 事件触发后调用。
     */
    fetchAndRender() {
        fetch('/api/game/llm_context')
            .then(r => r.json())
            .then(data => {
                if (data.status === 'no_context') {
                    this._showEmpty('等待 LLM 首次调用...（当前局面可能由规则引擎处理）');
                    return;
                }
                if (data.status === 'no_server') {
                    this._showEmpty('服务器未就绪');
                    return;
                }
                if (data.status !== 'ok') {
                    return;
                }
                // 检测是否有新的 LLM 调用（同一手牌内可能有多次调用）
                const handId = App.gameState ? App.gameState.hand_id : 0;
                const callIdx = data.call_index || 0;
                if (handId === this._lastHandId && callIdx === this._lastCallIndex) {
                    return; // 没有新的调用，不刷新
                }
                this._lastHandId = handId;
                this._lastCallIndex = callIdx;
                this._render(data);
            })
            .catch(err => {
                this._showEmpty('获取 LLM 上下文失败: ' + err.message);
            });
    },

    /**
     * 渲染 LLM 上下文到面板。
     */
    _render(data) {
        const container = document.getElementById('context-content');
        if (!container) return;

        const provider = data.provider || '?';
        const model = data.model || '?';
        const latency = data.latency_seconds != null ? data.latency_seconds.toFixed(2) + 's' : '?';
        const inputTokens = data.input_tokens || 0;
        const outputTokens = data.output_tokens || 0;
        const action = data.parsed_action || '?';
        const callIndex = data.call_index || 1;

        let html = '';

        // 元信息
        html += '<div class="context-meta">';
        html += `<span class="context-provider">${this._esc(provider)} / ${this._esc(model)}</span>`;
        html += `<span class="context-call">本手第 ${callIndex} 次调用</span>`;
        html += '</div>';

        html += '<div class="context-stats">';
        html += `<span>延迟: ${latency}</span>`;
        html += `<span>Tokens: in=${inputTokens} out=${outputTokens}</span>`;
        html += `<span>决策: ${this._esc(action)}</span>`;
        html += '</div>';

        // 桌面形象
        if (data.table_image) {
            const img = data.table_image;
            html += '<details class="context-section">';
            html += '<summary>桌面形象</summary>';
            html += `<div class="context-text">`;
            html += `形象: ${this._esc(img.image_label || '?')}<br>`;
            html += `进攻频率: ${(img.aggression_frequency * 100).toFixed(0)}%<br>`;
            html += `弃牌频率: ${(img.fold_frequency * 100).toFixed(0)}%`;
            html += `</div></details>`;
        }

        // 系统提示
        if (data.system_prompt) {
            html += '<details class="context-section">';
            html += '<summary>系统提示</summary>';
            html += `<pre class="context-text">${this._esc(data.system_prompt)}</pre>`;
            html += '</details>';
        }

        // 用户提示
        if (data.user_prompt) {
            html += '<details class="context-section" open>';
            html += '<summary>用户提示（完整 Prompt）</summary>';
            html += `<pre class="context-text context-prompt">${this._esc(data.user_prompt)}</pre>`;
            html += '</details>';
        }

        // LLM 回复
        if (data.raw_response) {
            html += '<details class="context-section" open>';
            html += '<summary>LLM 回复</summary>';
            html += `<pre class="context-text context-response">${this._esc(data.raw_response)}</pre>`;
            html += '</details>';
        }

        // 操作按钮
        html += '<div class="context-actions">';
        html += '<button class="btn-context-copy" onclick="ContextDebug._copyPrompt()">复制 Prompt</button>';
        html += '<button class="btn-context-copy" onclick="ContextDebug._copyResponse()">复制回复</button>';
        html += '</div>';

        container.innerHTML = html;
    },

    /**
     * 显示空状态。
     */
    _showEmpty(msg) {
        const container = document.getElementById('context-content');
        if (!container) return;
        container.innerHTML = `<div class="context-empty">${this._esc(msg)}</div>`;
    },

    /**
     * 复制完整 Prompt 到剪贴板。
     */
    _copyPrompt() {
        const pre = document.querySelector('.context-prompt');
        if (pre) {
            navigator.clipboard.writeText(pre.textContent).then(() => {
                this._flashButton('复制 Prompt ✓');
            }).catch(() => {
                this._flashButton('复制失败');
            });
        }
    },

    /**
     * 复制 LLM 回复到剪贴板。
     */
    _copyResponse() {
        const pre = document.querySelector('.context-response');
        if (pre) {
            navigator.clipboard.writeText(pre.textContent).then(() => {
                this._flashButton('复制回复 ✓');
            }).catch(() => {
                this._flashButton('复制失败');
            });
        }
    },

    /**
     * 短暂闪烁按钮文字。
     */
    _flashButton(text) {
        const btns = document.querySelectorAll('.btn-context-copy');
        btns.forEach(b => {
            const orig = b.textContent;
            b.textContent = text;
            setTimeout(() => { b.textContent = orig; }, 1500);
        });
    },

    /**
     * HTML 转义。
     */
    _esc(s) {
        if (!s) return '';
        return String(s)
            .replace(/&/g, '&amp;')
            .replace(/</g, '&lt;')
            .replace(/>/g, '&gt;')
            .replace(/"/g, '&quot;');
    },
};
