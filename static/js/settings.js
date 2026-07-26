/**
 * settings.js — LLM 设置面板（精简版）。
 */
const PROVIDER_PRESETS = {
    deepseek:  { name: 'DeepSeek（深度求索）', base_url: 'https://api.deepseek.com', models: ['deepseek-v4-pro', 'deepseek-v4-flash', 'deepseek-chat'], keyEnv: 'DEEPSEEK_API_KEY' },
    qwen:      { name: '通义千问（阿里云）', base_url: 'https://dashscope.aliyuncs.com/compatible-mode/v1', models: ['qwen3-max', 'qwen3-plus', 'qwen3-turbo'], keyEnv: 'DASHSCOPE_API_KEY' },
    glm:       { name: '智谱 GLM',  base_url: 'https://open.bigmodel.cn/api/paas/v4', models: ['glm-5.2', 'glm-5-turbo', 'glm-5-flash'], keyEnv: 'GLM_API_KEY' },
    kimi:      { name: 'Kimi（月之暗面）', base_url: 'https://api.moonshot.cn', models: ['kimi-k2.6', 'kimi-k2-turbo'], keyEnv: 'MOONSHOT_API_KEY' },
    minimax:   { name: 'MiniMax', base_url: 'https://api.minimaxi.com/v1', models: ['MiniMax-M3', 'MiniMax-M2'], keyEnv: 'MINIMAX_API_KEY' },
    volcengine:{ name: '火山引擎', base_url: 'https://ark.cn-beijing.volces.com/api/v3', models: ['doubao-pro', 'doubao-lite'], keyEnv: 'ARK_API_KEY' },
    longcat:   { name: 'LongCat（美团）', base_url: 'https://api.longcat.cn/v1', models: ['longcat-pro', 'longcat-flash'], keyEnv: 'LONGCAT_API_KEY' },
    openai:    { name: 'OpenAI (GPT)', base_url: '', models: ['gpt-4o', 'gpt-4o-mini'], keyEnv: 'OPENAI_API_KEY' },
    anthropic: { name: 'Anthropic (Claude)', base_url: '', models: ['claude-sonnet-4-20250514', 'claude-haiku-4-5-20251001'], keyEnv: 'ANTHROPIC_API_KEY' },
    ollama:    { name: 'Ollama (本地)', base_url: 'http://localhost:11434', models: ['llama3', 'qwen3'], keyEnv: '' },
};

const LLMSettings = {
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
        document.getElementById('llm-primary-provider').addEventListener('change', () => {
            this._onProviderChange();
        });
        const tempSlider = document.getElementById('llm-primary-temperature');
        tempSlider.addEventListener('input', () => {
            document.getElementById('llm-temp-val').textContent = parseFloat(tempSlider.value).toFixed(2);
        });
    },

    _onProviderChange() {
        const provider = document.getElementById('llm-primary-provider').value;
        const preset = PROVIDER_PRESETS[provider];
        if (!preset) return;

        const modelInput = document.getElementById('llm-primary-model');
        if (!preset.models.includes(modelInput.value)) {
            modelInput.value = preset.models[0];
        }
        let datalistId = 'llm-model-list';
        let datalist = document.getElementById(datalistId);
        if (!datalist) {
            datalist = document.createElement('datalist');
            datalist.id = datalistId;
            modelInput.setAttribute('list', datalistId);
            modelInput.parentNode.appendChild(datalist);
        }
        datalist.innerHTML = preset.models.map(m => `<option value="${m}">`).join('');

        const baseUrlInput = document.getElementById('llm-primary-base-url');
        if (!baseUrlInput.value || baseUrlInput.dataset.auto === 'true') {
            baseUrlInput.value = preset.base_url;
            baseUrlInput.dataset.auto = 'true';
        }
        baseUrlInput.addEventListener('input', () => { baseUrlInput.dataset.auto = 'false'; }, { once: true });

        const keyInput = document.getElementById('llm-primary-api-key');
        keyInput.placeholder = preset.keyEnv ? `留空则使用环境变量 ${preset.keyEnv}` : '留空则使用环境变量';
    },

    _loadSettings() {
        fetch('/api/config/llm')
            .then(r => r.json())
            .then(cfg => {
                const p = cfg.primary || {};
                const provider = p.provider || 'deepseek';
                document.getElementById('llm-primary-provider').value = provider;
                this._onProviderChange();
                document.getElementById('llm-primary-model').value = p.model || '';
                document.getElementById('llm-primary-api-key').value = p.api_key || '';
                const baseUrlInput = document.getElementById('llm-primary-base-url');
                if (p.base_url) { baseUrlInput.value = p.base_url; baseUrlInput.dataset.auto = 'false'; }
                document.getElementById('llm-primary-temperature').value = p.temperature ?? 0.5;
                document.getElementById('llm-temp-val').textContent = (p.temperature ?? 0.5).toFixed(2);
                document.getElementById('llm-reasoning-effort').value = p.reasoning_effort || 'disabled';
                document.getElementById('llm-primary-timeout').value = p.timeout_seconds || 60;
            })
            .catch(e => console.error('加载配置失败:', e));
    },

    _saveSettings() {
        const provider = document.getElementById('llm-primary-provider').value;
        const baseUrlInput = document.getElementById('llm-primary-base-url');
        let baseUrl = baseUrlInput.value.trim();
        if (!baseUrl && PROVIDER_PRESETS[provider]) {
            baseUrl = PROVIDER_PRESETS[provider].base_url;
        }

        const cfg = {
            primary: {
                provider,
                model: document.getElementById('llm-primary-model').value.trim(),
                api_key: document.getElementById('llm-primary-api-key').value,
                base_url: baseUrl,
                temperature: parseFloat(document.getElementById('llm-primary-temperature').value) || 0.5,
                timeout_seconds: parseInt(document.getElementById('llm-primary-timeout').value) || 60,
                reasoning_effort: document.getElementById('llm-reasoning-effort').value,
            },
        };

        fetch('/api/config/llm', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(cfg),
        })
        .then(r => r.json())
        .then(result => {
            if (result.error) { alert('保存失败: ' + result.error); }
            else {
                document.getElementById('modal-settings').style.display = 'none';
                alert('LLM 配置已保存！新游戏将使用新配置。');
            }
        })
        .catch(e => alert('保存失败: ' + e));
    },
};

document.addEventListener('DOMContentLoaded', () => LLMSettings.init());
