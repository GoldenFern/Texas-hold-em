/**
 * settings.js — LLM 编排设置面板（国内模型）。
 */

// 国内 LLM 提供商预设
const PROVIDER_PRESETS = {
    deepseek:  { name: 'DeepSeek',  base_url: 'https://api.deepseek.com',                          models: ['deepseek-v4-pro', 'deepseek-v4-flash'], keyEnv: 'DEEPSEEK_API_KEY', keyHint: '在 platform.deepseek.com 获取' },
    qwen:      { name: '通义千问 (Qwen)', base_url: 'https://dashscope.aliyuncs.com/compatible-mode/v1', models: ['qwen-3.7-max', 'qwen-3.7-plus'], keyEnv: 'DASHSCOPE_API_KEY', keyHint: '在 dashscope.aliyun.com 获取' },
    glm:       { name: '智谱 GLM',  base_url: 'https://open.bigmodel.cn/api/paas/v4',               models: ['glm-5.2', 'glm-5-turbo'], keyEnv: 'GLM_API_KEY', keyHint: '在 open.bigmodel.cn 获取' },
    kimi:      { name: 'Kimi (月之暗面)', base_url: 'https://api.moonshot.cn',                      models: ['kimi-k2.6'], keyEnv: 'MOONSHOT_API_KEY', keyHint: '在 platform.moonshot.cn 获取' },
    minimax:   { name: 'MiniMax',  base_url: 'https://api.minimaxi.com/v1',                        models: ['MiniMax-M3'], keyEnv: 'MINIMAX_API_KEY', keyHint: '在 platform.minimaxi.com 获取' },
    openai:    { name: 'OpenAI (GPT)', base_url: '',                                                 models: ['gpt-4o', 'gpt-4o-mini'], keyEnv: 'OPENAI_API_KEY', keyHint: '在 platform.openai.com 获取' },
    anthropic: { name: 'Anthropic (Claude)', base_url: '',                                           models: ['claude-sonnet-4-20250514', 'claude-haiku-4-5-20251001'], keyEnv: 'ANTHROPIC_API_KEY', keyHint: '在 console.anthropic.com 获取' },
    ollama:    { name: 'Ollama (本地)', base_url: 'http://localhost:11434',                           models: ['llama3', 'qwen3', 'deepseek-r1'], keyEnv: '', keyHint: '本地部署无需 API Key' },
};

const LLMSettings = {
    _fallbackCounter: 0,

    /** 初始化：绑定事件 */
    init() {
        document.getElementById('btn-settings').addEventListener('click', () => {
            this._loadSettings();
            document.getElementById('modal-settings').style.display = 'flex';
        });
        document.getElementById('btn-close-settings').addEventListener('click', () => {
            document.getElementById('modal-settings').style.display = 'none';
        });
        document.getElementById('btn-save-settings').addEventListener('click', () => {
            this._saveSettings();
        });
        document.getElementById('btn-add-fallback').addEventListener('click', () => {
            this._addFallbackRow();
        });

        // 提供商切换 → 更新模型列表 + base_url
        document.getElementById('llm-primary-provider').addEventListener('change', () => {
            this._onProviderChange();
        });

        // Temperature 滑块联动
        const tempSlider = document.getElementById('llm-primary-temperature');
        tempSlider.addEventListener('input', () => {
            document.getElementById('llm-temp-val').textContent =
                parseFloat(tempSlider.value).toFixed(2);
        });
    },

    /** 提供商切换时更新模型下拉和 base_url */
    _onProviderChange() {
        const provider = document.getElementById('llm-primary-provider').value;
        const preset = PROVIDER_PRESETS[provider];
        if (!preset) return;

        // 更新模型下拉
        const modelInput = document.getElementById('llm-primary-model');
        const currentModel = modelInput.value;
        if (!preset.models.includes(currentModel)) {
            modelInput.value = preset.models[0];
        }
        // 使用 datalist 提供模型建议
        let datalistId = 'llm-model-list';
        let datalist = document.getElementById(datalistId);
        if (!datalist) {
            datalist = document.createElement('datalist');
            datalist.id = datalistId;
            modelInput.setAttribute('list', datalistId);
            modelInput.parentNode.appendChild(datalist);
        }
        datalist.innerHTML = preset.models.map(m => `<option value="${m}">`).join('');

        // 更新 base_url
        const baseUrlInput = document.getElementById('llm-primary-base-url');
        if (!baseUrlInput.value || baseUrlInput.dataset.auto === 'true') {
            baseUrlInput.value = preset.base_url;
            baseUrlInput.dataset.auto = 'true';
        }
        // 手动修改 base_url 后取消自动填充标记
        baseUrlInput.addEventListener('input', () => { baseUrlInput.dataset.auto = 'false'; }, { once: true });

        // 更新 API Key 提示
        const keyInput = document.getElementById('llm-primary-api-key');
        keyInput.placeholder = preset.keyHint || ('环境变量: ' + preset.keyEnv);
    },

    /** 从服务器加载 LLM 配置 */
    _loadSettings() {
        fetch('/api/config/llm')
            .then(r => r.json())
            .then(cfg => {
                if (cfg.error) { alert('加载配置失败: ' + cfg.error); return; }

                // 主力模型
                const p = cfg.primary || {};
                const provider = p.provider || 'deepseek';
                document.getElementById('llm-primary-provider').value = provider;
                this._onProviderChange();
                document.getElementById('llm-primary-model').value = p.model || '';
                document.getElementById('llm-primary-api-key').value = p.api_key || '';
                const baseUrlInput = document.getElementById('llm-primary-base-url');
                if (p.base_url) {
                    baseUrlInput.value = p.base_url;
                    baseUrlInput.dataset.auto = 'false';
                }
                document.getElementById('llm-primary-temperature').value = p.temperature ?? 0.1;
                document.getElementById('llm-temp-val').textContent = (p.temperature ?? 0.1).toFixed(2);
                document.getElementById('llm-primary-max-tokens').value = p.max_tokens || 200;
                document.getElementById('llm-primary-timeout').value = p.timeout_seconds || 15;

                // 策略
                document.getElementById('llm-call-frequency').value = cfg.call_frequency || 'critical';
                document.getElementById('llm-min-decisions').value = cfg.min_llm_decisions_per_hand ?? 1;
                document.getElementById('llm-context-window').value = cfg.context_window_hands ?? 5;

                // 高级
                document.getElementById('llm-prompt-caching').checked = cfg.enable_prompt_caching !== false;
                document.getElementById('llm-commentary').checked = cfg.enable_commentary === true;
                document.getElementById('llm-advisor').checked = cfg.enable_advisor === true;

                // 降级链
                this._renderFallbacks(cfg.fallbacks || []);
            })
            .catch(e => alert('加载配置失败: ' + e));
    },

    /** 渲染降级链 */
    _renderFallbacks(fallbacks) {
        const container = document.getElementById('fallback-list');
        container.innerHTML = '';
        this._fallbackCounter = 0;

        fallbacks.forEach(fb => {
            this._addFallbackRow(fb);
        });

        if (fallbacks.length === 0) {
            container.innerHTML = '<p class="fallback-hint" style="color:#888;font-size:13px;">暂无降级模型（将使用规则引擎作为最终兜底）</p>';
        }
    },

    /** 添加一个降级链行 */
    _addFallbackRow(data = null) {
        const container = document.getElementById('fallback-list');
        const hint = container.querySelector('.fallback-hint');
        if (hint) hint.remove();

        const idx = ++this._fallbackCounter;
        const providerOpts = Object.entries(PROVIDER_PRESETS)
            .map(([k, v]) => `<option value="${k}" ${(data?.provider || 'deepseek') === k ? 'selected' : ''}>${v.name}</option>`)
            .join('');

        const row = document.createElement('div');
        row.className = 'fallback-row';
        row.innerHTML = `
            <span class="fallback-arrow">↳</span>
            <select class="fb-provider">${providerOpts}</select>
            <input type="text" class="fb-model" placeholder="模型 ID" value="${data?.model || ''}">
            <input type="number" class="fb-timeout" placeholder="超时(秒)" value="${data?.timeout_seconds || 10}" min="3" max="60" style="width:60px;">
            <button class="btn btn-sm btn-remove-fallback" title="移除">✕</button>
        `;
        // 降级链提供商切换 → 更新模型建议
        const fbSelect = row.querySelector('.fb-provider');
        const fbModel = row.querySelector('.fb-model');
        fbSelect.addEventListener('change', () => {
            const preset = PROVIDER_PRESETS[fbSelect.value];
            if (preset && preset.models.length > 0 && !preset.models.includes(fbModel.value)) {
                fbModel.value = preset.models[0];
            }
        });
        row.querySelector('.btn-remove-fallback').addEventListener('click', () => {
            row.remove();
            if (container.querySelectorAll('.fallback-row').length === 0) {
                container.innerHTML = '<p class="fallback-hint" style="color:#888;font-size:13px;">暂无降级模型（将使用规则引擎作为最终兜底）</p>';
            }
        });
        container.appendChild(row);
    },

    /** 保存 LLM 配置 */
    _saveSettings() {
        const primaryApiKey = document.getElementById('llm-primary-api-key').value;
        const provider = document.getElementById('llm-primary-provider').value;

        // 自动使用预设 base_url（如果未手动修改）
        const baseUrlInput = document.getElementById('llm-primary-base-url');
        let baseUrl = baseUrlInput.value.trim();
        if (!baseUrl && PROVIDER_PRESETS[provider]) {
            baseUrl = PROVIDER_PRESETS[provider].base_url;
        }

        // 收集降级链
        const fallbacks = [];
        document.querySelectorAll('.fallback-row').forEach(row => {
            const fbProvider = row.querySelector('.fb-provider').value;
            const model = row.querySelector('.fb-model').value.trim();
            const timeout = parseInt(row.querySelector('.fb-timeout').value) || 10;
            if (model) {
                const fbPreset = PROVIDER_PRESETS[fbProvider];
                fallbacks.push({
                    provider: fbProvider,
                    model,
                    timeout_seconds: timeout,
                    base_url: fbPreset ? fbPreset.base_url : '',
                });
            }
        });

        const cfg = {
            primary: {
                provider,
                model: document.getElementById('llm-primary-model').value.trim(),
                api_key: primaryApiKey,
                base_url: baseUrl,
                temperature: parseFloat(document.getElementById('llm-primary-temperature').value),
                max_tokens: parseInt(document.getElementById('llm-primary-max-tokens').value) || 200,
                timeout_seconds: parseInt(document.getElementById('llm-primary-timeout').value) || 15,
            },
            fallbacks,
            call_frequency: document.getElementById('llm-call-frequency').value,
            min_llm_decisions_per_hand: parseInt(document.getElementById('llm-min-decisions').value) || 1,
            context_window_hands: parseInt(document.getElementById('llm-context-window').value) || 5,
            enable_prompt_caching: document.getElementById('llm-prompt-caching').checked,
            enable_commentary: document.getElementById('llm-commentary').checked,
            enable_advisor: document.getElementById('llm-advisor').checked,
        };

        fetch('/api/config/llm', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(cfg),
        })
        .then(r => r.json())
        .then(result => {
            if (result.error) {
                alert('保存失败: ' + result.error);
            } else {
                document.getElementById('modal-settings').style.display = 'none';
                alert('✅ LLM 配置已保存！新游戏将使用新配置。');
            }
        })
        .catch(e => alert('保存失败: ' + e));
    },
};

document.addEventListener('DOMContentLoaded', () => LLMSettings.init());
