    const HISTORY_LIMIT = 5;
    const IDLE_STATE_REFRESH_EVERY = 4;
    const MAX_OBJECT_RENDER = 12;
    const MAX_ENTITY_RENDER = 30;
    let currentMode = 'governance';
    let relationState = null;
    let governanceState = null;
    let pipelineState = null;
    let currentRelationIndex = -1;
    let currentGovernanceIndex = -1;
    let relationHistory = [];
    let governanceHistory = [];
    let pipelineFormInitialized = false;
    let pipelineFormDirty = false;
    let pipelineFormBound = false;
    let settingsModalOpen = false;
    let idlePollCounter = 0;
    let lastPipelineLogSignature = '';
    let lastRawImagePath = '';
    let lastBevImagePath = '';
    let staticBevPath = '';
    let currentFrameId = '';
    let currentFocusEntities = [];
    let dynamicBevEnabled = false;
    let lastDynamicSignature = '';
    let currentBevOverlay = null;
    let slowdownLinkSelection = null;
    let slowdownLinkContext = null;
    let currentAnalysisTab = 'vehicle';
    let pedestrianCrossingSummary = null;
    let pedestrianSelectedEntity = '';
    let pedestrianWindowFrames = 60;
    let pedestrianBusyThreshold = 8;
    let pedestrianSaturatedThreshold = 14;
    let isZoomed = [false, false];
    let pipelinePolling = null;
    let lastPipelineRunning = false;
    let zoomLayersCache = [null, null];
    let panRafId = [0, 0];
    let panPendingOrigin = [null, null];

    const UI_PREFS_KEY = 'dair_console_ui_prefs_v1';
    let uiPrefs = {
        theme: 'system',
        density: 'comfortable',
        performanceMode: 'balanced',
        fontScale: 100,
        motionEnabled: true,
    };

    async function apiGet(url) {
        const res = await fetch(url);
        return await res.json();
    }

    async function apiPost(url, payload) {
        const res = await fetch(url, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(payload || {})
        });
        const body = await res.json();
        if (!res.ok) {
            throw new Error(body.message || '请求失败');
        }
        return body;
    }

    function _resolveUiTheme(theme) {
        if (theme === 'light' || theme === 'dark') return theme;
        return window.matchMedia && window.matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light';
    }

    function _normalizeUiPrefs(raw) {
        const themeRaw = String((raw && raw.theme) || 'system').toLowerCase();
        const densityRaw = String((raw && raw.density) || 'comfortable').toLowerCase();
        const fontScaleRaw = Number((raw && raw.fontScale) || 100);

        return {
            theme: ['system', 'light', 'dark'].includes(themeRaw) ? themeRaw : 'system',
            density: densityRaw === 'compact' ? 'compact' : 'comfortable',
            performanceMode: ((raw && raw.performanceMode) === 'rich') ? 'rich' : 'balanced',
            fontScale: Math.max(90, Math.min(115, Number.isFinite(fontScaleRaw) ? fontScaleRaw : 100)),
            motionEnabled: raw && typeof raw.motionEnabled === 'boolean' ? raw.motionEnabled : true,
        };
    }

    function loadAppearancePrefs() {
        try {
            const text = localStorage.getItem(UI_PREFS_KEY);
            if (!text) {
                uiPrefs = _normalizeUiPrefs(uiPrefs);
                return;
            }
            const parsed = JSON.parse(text);
            uiPrefs = _normalizeUiPrefs(parsed);
        } catch (err) {
            console.warn('appearance prefs load failed', err);
            uiPrefs = _normalizeUiPrefs(uiPrefs);
        }
    }

    function saveAppearancePrefs() {
        try {
            localStorage.setItem(UI_PREFS_KEY, JSON.stringify(uiPrefs));
        } catch (err) {
            console.warn('appearance prefs save failed', err);
        }
    }

    function applyAppearancePrefs() {
        const root = document.documentElement;
        const theme = _resolveUiTheme(uiPrefs.theme);
        root.setAttribute('data-theme', theme);
        root.setAttribute('data-density', uiPrefs.density);
        root.setAttribute('data-performance', uiPrefs.performanceMode);
        root.setAttribute('data-motion', uiPrefs.motionEnabled ? 'on' : 'off');
        root.style.fontSize = `${uiPrefs.fontScale}%`;

        const scaleValue = document.getElementById('ui-font-scale-value');
        if (scaleValue) scaleValue.innerText = `${uiPrefs.fontScale}%`;
    }

    function syncAppearanceControls() {
        const themeSelect = document.getElementById('ui-theme-select');
        const densitySelect = document.getElementById('ui-density-select');
        const performanceSelect = document.getElementById('ui-performance-select');
        const fontSlider = document.getElementById('ui-font-scale');
        const motionToggle = document.getElementById('ui-motion-toggle');

        if (themeSelect) themeSelect.value = uiPrefs.theme;
        if (densitySelect) densitySelect.value = uiPrefs.density;
        if (performanceSelect) performanceSelect.value = uiPrefs.performanceMode;
        if (fontSlider) fontSlider.value = String(uiPrefs.fontScale);
        if (motionToggle) motionToggle.checked = !!uiPrefs.motionEnabled;
        applyAppearancePrefs();
    }

    function closeAppearancePanel() {
        const panel = document.getElementById('appearance-panel');
        if (panel) panel.classList.remove('active');
    }

    function toggleAppearancePanel(event) {
        if (event) event.stopPropagation();
        const panel = document.getElementById('appearance-panel');
        if (!panel) return;
        panel.classList.toggle('active');
    }

    function bindAppearanceControls() {
        const panel = document.getElementById('appearance-panel');
        const themeSelect = document.getElementById('ui-theme-select');
        const densitySelect = document.getElementById('ui-density-select');
        const performanceSelect = document.getElementById('ui-performance-select');
        const fontSlider = document.getElementById('ui-font-scale');
        const motionToggle = document.getElementById('ui-motion-toggle');

        if (panel) {
            panel.addEventListener('click', (event) => event.stopPropagation());
        }

        if (themeSelect) {
            themeSelect.addEventListener('change', () => {
                uiPrefs.theme = String(themeSelect.value || 'system');
                saveAppearancePrefs();
                applyAppearancePrefs();
            });
        }

        if (densitySelect) {
            densitySelect.addEventListener('change', () => {
                uiPrefs.density = String(densitySelect.value || 'comfortable');
                saveAppearancePrefs();
                applyAppearancePrefs();
            });
        }

        if (performanceSelect) {
            performanceSelect.addEventListener('change', () => {
                uiPrefs.performanceMode = String(performanceSelect.value || 'balanced') === 'rich' ? 'rich' : 'balanced';
                saveAppearancePrefs();
                applyAppearancePrefs();
                setupPolling();
            });
        }

        if (fontSlider) {
            fontSlider.addEventListener('input', () => {
                uiPrefs.fontScale = Math.max(90, Math.min(115, Number(fontSlider.value || 100)));
                applyAppearancePrefs();
            });
            fontSlider.addEventListener('change', () => {
                saveAppearancePrefs();
            });
        }

        if (motionToggle) {
            motionToggle.addEventListener('change', () => {
                uiPrefs.motionEnabled = !!motionToggle.checked;
                saveAppearancePrefs();
                applyAppearancePrefs();
            });
        }

        if (window.matchMedia) {
            const media = window.matchMedia('(prefers-color-scheme: dark)');
            const listener = () => {
                if (uiPrefs.theme === 'system') {
                    applyAppearancePrefs();
                }
            };
            if (typeof media.addEventListener === 'function') {
                media.addEventListener('change', listener);
            } else if (typeof media.addListener === 'function') {
                media.addListener(listener);
            }
        }

        document.addEventListener('click', () => {
            closeAppearancePanel();
        });
    }

    function resetAppearancePrefs() {
        uiPrefs = {
            theme: 'system',
            density: 'comfortable',
            performanceMode: 'balanced',
            fontScale: 100,
            motionEnabled: true,
        };
        saveAppearancePrefs();
        syncAppearanceControls();
    }

    

