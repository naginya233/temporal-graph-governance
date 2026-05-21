let signalSettingsBound = false;
let signalSettingsDirty = false;
let signalHlsInstance = null;
let signalRealtimeTimer = null;
let signalRealtimeTickTimer = null;
let signalRealtimeState = null;

const SIGNAL_REPLAY_PRESET_PATHS = {
    conflict: '/app/docs/examples/replay_conflict.json',
    normal: '/app/docs/examples/replay_normal.json',
};
const SIGNAL_DEFAULT_TEMPLATE_PATH = '/app/docs/examples/conflict_6phase_manual.cmts';
const SIGNAL_DEFAULT_PHASE_SEMANTICS = {
    1: { ring: 1, channels: [1, 7], description: '西北左转 + 东直行' },
    2: { ring: 2, channels: [13], description: '南进口人行' },
    3: { ring: 3, channels: [3, 8], description: '东左转 + 南直行/右转' },
    4: { ring: 1, channels: [4, 5], description: '南左转 + 西北直行' },
    5: { ring: 2, channels: [16], description: '东进口人行/西北人行接线相关' },
    6: { ring: 1, channels: [12], description: '西北进口人行/接线相关' },
    7: { ring: 2, channels: [], description: '虚相位，补齐 Ring2 周期' },
    8: { ring: 3, channels: [], description: '虚相位，补齐 Ring3 周期' },
};
const SIGNAL_DEFAULT_CHANNEL_MAP = {
    1: { approach: '西北进口', movement: '左转', type: 'motor' },
    5: { approach: '西北进口', movement: '直行', type: 'motor' },
    12: { approach: '西北进口', movement: '人行/接线异常', type: 'pedestrian' },
    3: { approach: '东进口', movement: '左转', type: 'motor' },
    7: { approach: '东进口', movement: '直行', type: 'motor' },
    16: { approach: '东进口/西北进口', movement: '人行/接线共用', type: 'pedestrian' },
    4: { approach: '南进口', movement: '左转', type: 'motor' },
    8: { approach: '南进口', movement: '直行/右转', type: 'motor' },
    13: { approach: '南进口', movement: '人行', type: 'pedestrian' },
};

function _signalById(id) {
    return document.getElementById(id);
}

function _signalConfig() {
    return relationState && relationState.config ? relationState.config : {};
}

function bindSignalConsoleEvents() {
    if (signalSettingsBound) return;
    signalSettingsBound = true;

    const ids = [
        'signal-agent-base-url',
        'signal-session-id',
        'signal-profile',
        'signal-agent-timeout',
        'signal-controller-host',
        'signal-controller-port',
        'signal-controller-timeout',
        'signal-controller-poll-interval',
        'signal-send-mode',
        'signal-cmts-profile-preset',
        'signal-cmts-replay-profile',
        'signal-cmts-template-path',
        'signal-cmts-output-path',
        'signal-phase-p1',
        'signal-phase-p2',
        'signal-phase-p6',
        'signal-phase-p3',
        'signal-phase-p4',
        'signal-phase-p7',
        'signal-phase-p8',
        'signal-phase-seq',
        'signal-phase-gap-ms',
        'signal-phase-ack-timeout',
        'signal-phase-verify-ack',
        'signal-generate-download-after',
        'signal-phase-context',
        'signal-phase-objective',
        'signal-phase-semantics-json',
        'signal-channel-map-json',
        'signal-video-stream-url',
        'signal-stream-base-url',
        'signal-stream-device-id',
        'signal-stream-channel',
        'signal-viz-api-url',
    ];

    ids.forEach((id) => {
        const el = _signalById(id);
        if (!el) return;
        const eventName = (el.type === 'checkbox' || el.tagName === 'SELECT') ? 'change' : 'input';
        el.addEventListener(eventName, () => {
            signalSettingsDirty = true;
            if (id === 'signal-cmts-profile-preset') {
                _applySignalReplayPreset();
            }
            if (id === 'signal-cmts-replay-profile') {
                _syncSignalReplayPresetFromPath();
            }
            updateDerivedSignalPhaseFields();
            if (id === 'signal-stream-base-url' || id === 'signal-stream-device-id' || id === 'signal-stream-channel') {
                updateAutoSignalStreamUrl();
            }
        });
    });

    const textArea = _signalById('signal-chat-input');
    if (textArea) {
        textArea.addEventListener('keydown', async (event) => {
            if (event.key === 'Enter' && !event.shiftKey) {
                event.preventDefault();
                await sendSignalMessage();
            }
        });
    }

    const confirmBox = _signalById('signal-high-risk-confirmed');
    if (confirmBox) {
        // Per-request safety confirmation should not trigger config persistence.
        confirmBox.addEventListener('change', () => {
            updateProgressAndMeta();
        });
    }
}

function _normalizeStreamBaseUrl(value) {
    const text = String(value || '').trim();
    if (!text) return 'https://172.25.157.48:18083';
    if (text.startsWith('http://') || text.startsWith('https://')) return text.replace(/\/+$/, '');
    return `https://${text}`.replace(/\/+$/, '');
}

function _buildAutoStreamUrl() {
    const base = _normalizeStreamBaseUrl((_signalById('signal-stream-base-url') || {}).value);
    const deviceId = String(((_signalById('signal-stream-device-id') || {}).value) || '2-27').trim() || '2-27';
    const channelRaw = Number(((_signalById('signal-stream-channel') || {}).value) || 0);
    const channel = Number.isFinite(channelRaw) ? Math.max(0, Math.min(64, channelRaw)) : 0;
    return `${base}/stream/${encodeURIComponent(deviceId)}/channel/${channel}/hls/live/index.m3u8`;
}

function updateAutoSignalStreamUrl() {
    const autoUrl = _buildAutoStreamUrl();
    const autoInput = _signalById('signal-auto-stream-url');
    const openLink = _signalById('signal-open-stream-link');
    if (autoInput) autoInput.value = autoUrl;

    const manual = String(((_signalById('signal-video-stream-url') || {}).value) || '').trim();
    const effective = manual || autoUrl;
    if (openLink) openLink.href = effective || '#';
    return autoUrl;
}

function _setSignalVideoStatus(text) {
    const node = _signalById('signal-video-status');
    if (node) node.innerText = text;
}

function _destroySignalHls() {
    if (signalHlsInstance && typeof signalHlsInstance.destroy === 'function') {
        signalHlsInstance.destroy();
    }
    signalHlsInstance = null;
}

async function playSignalStream(url, sourceLabel) {
    const player = _signalById('signal-video-player');
    if (!player) return;

    const streamUrl = String(url || '').trim();
    if (!streamUrl) {
        _setSignalVideoStatus('未提供视频流地址。');
        return;
    }

    _destroySignalHls();
    player.pause();
    player.removeAttribute('src');
    player.load();

    try {
        const canUseHlsJs = typeof window.Hls !== 'undefined' && window.Hls && window.Hls.isSupported && window.Hls.isSupported();
        const isM3u8 = /\.m3u8($|\?)/i.test(streamUrl);

        if (canUseHlsJs && isM3u8) {
            signalHlsInstance = new window.Hls({
                lowLatencyMode: true,
                backBufferLength: 30,
            });
            signalHlsInstance.attachMedia(player);
            signalHlsInstance.on(window.Hls.Events.MEDIA_ATTACHED, () => {
                signalHlsInstance.loadSource(streamUrl);
            });
            signalHlsInstance.on(window.Hls.Events.ERROR, (_, data) => {
                _setSignalVideoStatus(`HLS 播放异常: ${data && data.type ? data.type : 'unknown'}`);
            });
            _setSignalVideoStatus(`已加载 ${sourceLabel}，正在播放...`);
        } else {
            player.src = streamUrl;
            _setSignalVideoStatus(`已加载 ${sourceLabel}，正在播放...`);
        }

        await player.play();
    } catch (err) {
        _setSignalVideoStatus(`播放失败: ${err.message || err}。如果是证书问题，请先在浏览器直接打开流地址信任证书。`);
    }
}

function stopSignalStream() {
    const player = _signalById('signal-video-player');
    if (!player) return;
    _destroySignalHls();
    player.pause();
    player.removeAttribute('src');
    player.load();
    _setSignalVideoStatus('已停止播放。');
}

async function applyAutoSignalStream() {
    const autoUrl = updateAutoSignalStreamUrl();
    const manualInput = _signalById('signal-video-stream-url');
    if (manualInput && !String(manualInput.value || '').trim()) {
        manualInput.value = autoUrl;
    }
    await playSignalStream(autoUrl, '自动拼接链接');
}

async function playManualSignalStream() {
    const manual = String(((_signalById('signal-video-stream-url') || {}).value) || '').trim();
    const fallback = updateAutoSignalStreamUrl();
    const effective = manual || fallback;
    await playSignalStream(effective, manual ? '手动链接' : '自动拼接链接');
}

function _deriveSignalPhaseP4() {
    const p1 = Number(((_signalById('signal-phase-p1') || {}).value) || NaN);
    const p2 = Number(((_signalById('signal-phase-p2') || {}).value) || NaN);
    const p6 = Number(((_signalById('signal-phase-p6') || {}).value) || NaN);
    const p4Input = _signalById('signal-phase-p4');

    if (!Number.isFinite(p1) || !Number.isFinite(p2) || !Number.isFinite(p6)) {
        if (p4Input) p4Input.value = '';
        return '';
    }

    const p4 = p1 + p6 - p2;
    if (p4Input) p4Input.value = String(p4);
    return String(p4);
}

function updateDerivedSignalPhaseFields() {
    _deriveSignalPhaseP4();
}

function _formatSignalJson(value) {
    return JSON.stringify(value, null, 2);
}

function _parseSignalJsonField(id, label) {
    const node = _signalById(id);
    const raw = String((node && node.value) || '').trim();
    if (!raw) return { value: null, error: '' };
    try {
        return { value: JSON.parse(raw), error: '' };
    } catch (err) {
        return { value: null, error: `${label} 不是合法 JSON: ${err.message || err}` };
    }
}

function _buildGenerateCmtsSpec() {
    const templatePath = String(((_signalById('signal-cmts-template-path') || {}).value) || '').trim();
    const outputPath = String(((_signalById('signal-cmts-output-path') || {}).value) || '').trim();
    const downloadAfterGenerate = !!((_signalById('signal-generate-download-after') || {}).checked);
    const phaseSemantics = _parseSignalJsonField('signal-phase-semantics-json', '相位语义 JSON');
    const channelMap = _parseSignalJsonField('signal-channel-map-json', '通道语义 JSON');

    if (!templatePath) {
        return { error: '请先填写模板 `.cmts` 路径。' };
    }
    if (phaseSemantics.error) return { error: phaseSemantics.error };
    if (channelMap.error) return { error: channelMap.error };

    const phaseInfo = _buildDownloadCmtsPhaseDurations();
    return {
        error: '',
        template_path: templatePath,
        output_path: outputPath || '',
        download_after_generate: downloadAfterGenerate,
        phase_durations: phaseInfo.phase_durations,
        missing_phase_durations: phaseInfo.missing || [],
        phase_semantics: phaseSemantics.value || SIGNAL_DEFAULT_PHASE_SEMANTICS,
        channel_map: channelMap.value || SIGNAL_DEFAULT_CHANNEL_MAP,
    };
}

function _syncSignalReplayPresetFromPath() {
    const preset = _signalById('signal-cmts-profile-preset');
    const profileInput = _signalById('signal-cmts-replay-profile');
    if (!preset || !profileInput) return;

    const current = String(profileInput.value || '').trim();
    const matched = Object.entries(SIGNAL_REPLAY_PRESET_PATHS).find(([, path]) => path === current);
    preset.value = matched ? matched[0] : 'custom';
}

function _applySignalReplayPreset() {
    const preset = _signalById('signal-cmts-profile-preset');
    const profileInput = _signalById('signal-cmts-replay-profile');
    if (!preset || !profileInput) return;

    const selected = String(preset.value || 'custom').trim();
    if (selected === 'custom') {
        _syncSignalReplayPresetFromPath();
        return;
    }

    const nextPath = SIGNAL_REPLAY_PRESET_PATHS[selected];
    if (!nextPath) return;
    profileInput.value = nextPath;
}

function fillSignalSettingsFromConfig() {
    const cfg = _signalConfig();
    if (signalSettingsDirty) return;

    const base = _signalById('signal-agent-base-url');
    const session = _signalById('signal-session-id');
    const profile = _signalById('signal-profile');
    const timeout = _signalById('signal-agent-timeout');
    const sendMode = _signalById('signal-send-mode');
    const cmtsPreset = _signalById('signal-cmts-profile-preset');
    const cmtsReplayProfile = _signalById('signal-cmts-replay-profile');
    const cmtsTemplatePath = _signalById('signal-cmts-template-path');
    const cmtsOutputPath = _signalById('signal-cmts-output-path');
    const phaseP1 = _signalById('signal-phase-p1');
    const phaseP2 = _signalById('signal-phase-p2');
    const phaseP6 = _signalById('signal-phase-p6');
    const phaseP3 = _signalById('signal-phase-p3');
    const phaseP4 = _signalById('signal-phase-p4');
    const phaseP7 = _signalById('signal-phase-p7');
    const phaseP8 = _signalById('signal-phase-p8');
    const phaseSeq = _signalById('signal-phase-seq');
    const phaseGapMs = _signalById('signal-phase-gap-ms');
    const phaseAckTimeout = _signalById('signal-phase-ack-timeout');
    const phaseVerifyAck = _signalById('signal-phase-verify-ack');
    const generateDownloadAfter = _signalById('signal-generate-download-after');
    const phaseContext = _signalById('signal-phase-context');
    const phaseObjective = _signalById('signal-phase-objective');
    const phaseSemanticsJson = _signalById('signal-phase-semantics-json');
    const channelMapJson = _signalById('signal-channel-map-json');
    const controllerHost = _signalById('signal-controller-host');
    const controllerPort = _signalById('signal-controller-port');
    const controllerTimeout = _signalById('signal-controller-timeout');
    const controllerPollInterval = _signalById('signal-controller-poll-interval');
    const streamUrl = _signalById('signal-video-stream-url');
    const streamBase = _signalById('signal-stream-base-url');
    const streamDeviceId = _signalById('signal-stream-device-id');
    const streamChannel = _signalById('signal-stream-channel');
    const vizUrl = _signalById('signal-viz-api-url');

    if (base) base.value = cfg.signal_agent_base_url || 'http://nl-agent:9001';
    if (session) session.value = cfg.signal_default_session_id || 'traffic-console-default';
    if (profile) profile.value = cfg.signal_default_profile || 'readonly';
    if (timeout) timeout.value = Number(cfg.signal_agent_timeout || 45);
    if (sendMode) sendMode.value = cfg.signal_send_mode || 'private_timing';
    if (cmtsPreset) cmtsPreset.value = 'custom';
    if (cmtsReplayProfile) cmtsReplayProfile.value = cfg.signal_cmts_replay_profile || '';
    if (cmtsTemplatePath) cmtsTemplatePath.value = cfg.signal_cmts_template_path || SIGNAL_DEFAULT_TEMPLATE_PATH;
    if (cmtsOutputPath) cmtsOutputPath.value = cfg.signal_cmts_output_path || '';
    if (phaseP1) phaseP1.value = cfg.signal_phase_p1 || '';
    if (phaseP2) phaseP2.value = cfg.signal_phase_p2 || '';
    if (phaseP6) phaseP6.value = cfg.signal_phase_p6 || '';
    if (phaseP3) phaseP3.value = cfg.signal_phase_p3 || '';
    if (phaseP4) phaseP4.value = cfg.signal_phase_p4 || '';
    if (phaseP7) phaseP7.value = cfg.signal_phase_p7 || '';
    if (phaseP8) phaseP8.value = cfg.signal_phase_p8 || '';
    if (phaseSeq) phaseSeq.value = cfg.signal_phase_seq || '';
    if (phaseGapMs) phaseGapMs.value = Number(cfg.signal_phase_gap_ms || 30);
    if (phaseAckTimeout) phaseAckTimeout.value = Number(cfg.signal_phase_ack_timeout || 1.0);
    if (phaseVerifyAck) phaseVerifyAck.checked = cfg.signal_phase_verify_ack !== false;
    if (generateDownloadAfter) generateDownloadAfter.checked = cfg.signal_generate_download_after === true;
    if (phaseContext) phaseContext.value = cfg.signal_phase_context || '';
    if (phaseObjective) phaseObjective.value = cfg.signal_phase_objective || '';
    if (phaseSemanticsJson) phaseSemanticsJson.value = cfg.signal_phase_semantics_json || _formatSignalJson(SIGNAL_DEFAULT_PHASE_SEMANTICS);
    if (channelMapJson) channelMapJson.value = cfg.signal_channel_map_json || _formatSignalJson(SIGNAL_DEFAULT_CHANNEL_MAP);
    if (controllerHost) controllerHost.value = cfg.signal_controller_host || '172.25.157.48';
    if (controllerPort) controllerPort.value = Number(cfg.signal_controller_port || 38083);
    if (controllerTimeout) controllerTimeout.value = Number(cfg.signal_controller_timeout || 1.0);
    if (controllerPollInterval) controllerPollInterval.value = Number(cfg.signal_controller_poll_interval || 6.0);
    if (streamUrl) streamUrl.value = cfg.signal_video_stream_url || '';
    if (streamBase) streamBase.value = cfg.signal_stream_base_url || 'https://172.25.157.48:18083';
    if (streamDeviceId) streamDeviceId.value = cfg.signal_stream_device_id || '2-27';
    if (streamChannel) streamChannel.value = Number(cfg.signal_stream_channel || 0);
    if (vizUrl) vizUrl.value = cfg.signal_visualization_api_url || '';
    _syncSignalReplayPresetFromPath();
    updateAutoSignalStreamUrl();
    updateDerivedSignalPhaseFields();
}

function setSignalLayoutActive(active) {
    const show = !!active;
    const signalPanel = _signalById('signal-panel');
    const pipelinePanel = _signalById('pipeline-panel');
    const banner = document.querySelector('.panel.banner');
    const workspace = _signalById('workspace');
    const actionBar = _signalById('action-bar');
    const done = _signalById('done-view');
    const analysis = _signalById('analysis-panel');

    if (signalPanel) signalPanel.style.display = show ? 'block' : 'none';

    if (show) {
        if (pipelinePanel) pipelinePanel.style.display = 'none';
        if (banner && banner.classList && banner.classList.contains('banner')) banner.style.display = 'none';
        if (workspace) workspace.style.display = 'none';
        if (actionBar) actionBar.style.display = 'none';
        if (analysis) analysis.classList.remove('show');
        if (done) done.classList.remove('show');
        return;
    }

    stopSignalRealtimePolling();

    if (banner && banner.classList && banner.classList.contains('banner')) banner.style.display = 'flex';
    if (workspace) workspace.style.display = 'grid';
    if (actionBar) actionBar.style.display = 'flex';
}

function _setSignalHealthStatus(ok, text, pending = false) {
    const pill = _signalById('signal-health-pill');
    const label = _signalById('signal-health-text');
    if (!pill || !label) return;

    pill.classList.remove('ok', 'bad', 'pending');
    if (pending) {
        pill.classList.add('pending');
        pill.innerText = '检测中';
    } else if (ok) {
        pill.classList.add('ok');
        pill.innerText = '在线';
    } else {
        pill.classList.add('bad');
        pill.innerText = '离线';
    }
    label.innerText = text || '';
}

function _setSignalRealtimeStatus(ok, text, pending = false) {
    const pill = _signalById('signal-realtime-pill');
    const label = _signalById('signal-realtime-text');
    if (!pill || !label) return;

    pill.classList.remove('ok', 'bad', 'pending');
    if (pending) {
        pill.classList.add('pending');
        pill.innerText = '刷新中';
    } else if (ok) {
        pill.classList.add('ok');
        pill.innerText = '在线';
    } else {
        pill.classList.add('bad');
        pill.innerText = '离线';
    }
    label.innerText = text || '';
}

function _clearSignalRealtimeTimer() {
    if (signalRealtimeTimer) {
        clearTimeout(signalRealtimeTimer);
    }
    signalRealtimeTimer = null;
}

function _clearSignalRealtimeTickTimer() {
    if (signalRealtimeTickTimer) {
        clearInterval(signalRealtimeTickTimer);
    }
    signalRealtimeTickTimer = null;
}

function _startSignalRealtimeTicking() {
    _clearSignalRealtimeTickTimer();
    const panel = _signalById('signal-panel');
    if (!panel || panel.style.display === 'none') return;

    signalRealtimeTickTimer = window.setInterval(() => {
        if (!signalRealtimeState || !signalRealtimeState.ok) return;
        _renderSignalRealtimeState(signalRealtimeState);
    }, 1000);
}

function _getSignalRealtimePollIntervalMs() {
    const raw = Number(((_signalById('signal-controller-poll-interval') || {}).value) || 6.0);
    if (!Number.isFinite(raw)) return 6000;
    return Math.max(1000, Math.min(60000, raw * 1000));
}

function _scheduleSignalRealtimePolling() {
    _clearSignalRealtimeTimer();
    signalRealtimeTimer = window.setTimeout(() => {
        refreshSignalRealtimeState(false);
    }, _getSignalRealtimePollIntervalMs());
}

function _buildSignalPhaseStateKey(state) {
    const heartbeat = state && state.heartbeat ? state.heartbeat : {};
    const detail = state && state.detail ? state.detail : {};
    const active = Array.isArray(state && state.active_phases) ? state.active_phases : [];
    const normalizedPhase = detail.phase_index !== undefined && detail.phase_index !== null
        ? Number(detail.phase_index)
        : (detail.phase_code !== undefined && detail.phase_code !== null ? Number(detail.phase_code) : null);

    if (Number.isFinite(normalizedPhase)) {
        return `phase:${normalizedPhase}`;
    }
    if (active.length) {
        return `active:${active.join(',')}`;
    }
    return `lamp:${String(heartbeat.lamp_state || 'unknown')}`;
}

function _readSignalPhaseDuration(id) {
    const raw = Number(((_signalById(id) || {}).value) || NaN);
    return Number.isFinite(raw) && raw > 0 ? raw : null;
}

function _getSignalConfiguredDurationByPhase(phaseCode) {
    const durations = {
        1: _readSignalPhaseDuration('signal-phase-p1'),
        2: _readSignalPhaseDuration('signal-phase-p2'),
        3: _readSignalPhaseDuration('signal-phase-p3'),
        4: _readSignalPhaseDuration('signal-phase-p4'),
        5: _readSignalPhaseDuration('signal-phase-p3'),
        6: _readSignalPhaseDuration('signal-phase-p6'),
    };
    if (!Number.isFinite(phaseCode)) return null;
    return durations[phaseCode] || null;
}

function _deriveSignalClockSnapshot(state, nowMs) {
    const detail = state && state.detail ? state.detail : {};
    const phaseCode = detail.phase_index !== undefined && detail.phase_index !== null
        ? Number(detail.phase_index)
        : (detail.phase_code !== undefined && detail.phase_code !== null ? Number(detail.phase_code) : null);
    const elapsed = Number(detail.elapsed_seconds);
    const total = Number(detail.total_seconds);
    const remaining = Number(detail.remaining_seconds);
    const configuredTotal = _getSignalConfiguredDurationByPhase(phaseCode);
    const hasRealtimeClock = !!detail.ok && Number.isFinite(elapsed) && (Number.isFinite(total) || Number.isFinite(remaining));
    const hasClock = hasRealtimeClock || (Number.isFinite(phaseCode) && Number.isFinite(configuredTotal));

    if (!hasClock) {
        return {
            hasClock: false,
            stateKey: _buildSignalPhaseStateKey(state),
            liveElapsed: 0,
        };
    }

    const baseElapsed = Number.isFinite(elapsed) ? Math.max(0, elapsed) : 0;
    const backendTotal = Number.isFinite(total)
        ? Math.max(baseElapsed, total)
        : (Number.isFinite(remaining) ? Math.max(baseElapsed + Math.max(0, remaining), baseElapsed) : null);
    const baseTotal = Number.isFinite(backendTotal)
        ? backendTotal
        : (Number.isFinite(configuredTotal) ? Math.max(baseElapsed, configuredTotal) : baseElapsed);
    const syncedAt = Number(state && state._frontend_synced_at_ms ? state._frontend_synced_at_ms : 0);
    const deltaSec = syncedAt ? Math.max(0, Math.floor((nowMs - syncedAt) / 1000)) : 0;

    return {
        hasClock: true,
        stateKey: _buildSignalPhaseStateKey(state),
        elapsed: baseElapsed,
        total: baseTotal,
        liveElapsed: Math.min(baseTotal, baseElapsed + deltaSec),
    };
}

function _renderSignalRealtimeState(state) {
    const root = _signalById('signal-realtime-state');
    const updated = _signalById('signal-realtime-updated');
    const raw = _signalById('signal-realtime-raw');
    const light = _signalById('signal-realtime-light');
    const statusText = _signalById('signal-realtime-status-text');
    const realtimeText = _signalById('signal-realtime-text');

    const heartbeat = state && state.heartbeat ? state.heartbeat : {};
    const detail = state && state.detail ? state.detail : {};
    const lamps = state && typeof state.phase_lamps === 'object' && state.phase_lamps
        ? state.phase_lamps
        : (heartbeat && typeof heartbeat.phase_lamps === 'object' ? heartbeat.phase_lamps : {});
    const ok = !!(state && state.ok);
    let lampState = 'unknown';
    const phaseCode = detail.phase_index !== undefined && detail.phase_index !== null
        ? Number(detail.phase_index)
        : (detail.phase_code !== undefined && detail.phase_code !== null ? Number(detail.phase_code) : null);
    const dualRingPairMap = { 1: 2, 2: 1, 6: 4, 4: 6, 3: 5, 5: 3 };
    const pairedPhaseCode = Number.isFinite(phaseCode) ? dualRingPairMap[phaseCode] : null;
    const clock = _deriveSignalClockSnapshot(state, Date.now());
    const liveElapsed = clock.hasClock ? clock.liveElapsed : 0;
    const liveRemaining = clock.hasClock ? Math.max(clock.total - clock.liveElapsed, 0) : 0;
    const activePhases = [];

    for (let i = 1; i <= 6; i += 1) {
        const row = _signalById(`signal-realtime-row-${i}`);
        const dot = _signalById(`signal-realtime-dot-${i}`);
        const status = _signalById(`signal-realtime-status-${i}`);
        const lamp = _signalById(`signal-realtime-lamp-${i}`);
        const elapsed = _signalById(`signal-realtime-elapsed-${i}`);
        const remaining = _signalById(`signal-realtime-remaining-${i}`);

        const key = `p${i}`;
        const info = lamps && lamps[key] ? lamps[key] : null;
        const isGreen = !!(info && info.green);
        const isCurrent = Number.isFinite(phaseCode) && phaseCode === i;
        const isPairedCurrent = Number.isFinite(pairedPhaseCode) && pairedPhaseCode === i;
        const isDisplayGreen = isGreen || isCurrent || isPairedCurrent;

        if (isDisplayGreen) {
            activePhases.push(`P${i}`);
        }

        if (dot) {
            dot.classList.remove('signal-realtime-dot-red', 'signal-realtime-dot-amber', 'signal-realtime-dot-green');
            dot.classList.add(isDisplayGreen ? 'signal-realtime-dot-green' : 'signal-realtime-dot-red');
        }
        if (status) {
            status.innerText = isDisplayGreen ? '放行' : '禁止';
        }
        if (lamp) {
            lamp.innerText = isDisplayGreen ? '绿灯' : '红灯';
        }
        if (elapsed) {
            elapsed.innerText = ((isCurrent || isPairedCurrent) && clock.hasClock) ? `${liveElapsed}s` : '--';
        }
        if (remaining) {
            remaining.innerText = ((isCurrent || isPairedCurrent) && clock.hasClock) ? `${liveRemaining}s` : '--';
        }
        if (row) {
            row.dataset.active = isDisplayGreen ? 'true' : 'false';
        }
    }

    const lampText = activePhases.length
        ? `${activePhases.join('/')} 放行`
        : (heartbeat.lamp_state || (ok ? '全红/切换中' : '离线'));

    const phaseCodeText = detail.phase_code !== undefined && detail.phase_code !== null
        ? `${detail.phase_code}`
        : '--';
    const phaseHeadText = detail.phase_label
        || (Number.isFinite(phaseCode) ? `P${phaseCode}` : '')
        || (activePhases.length ? activePhases.join('/') : '未识别');
    const headline = clock.hasClock
        ? `相位: ${phaseHeadText}，${lampText}；当前相位码 ${phaseCodeText}，已过 ${liveElapsed}s / ${clock.total}s，剩余 ${liveRemaining}s`
        : `相位: ${phaseHeadText}，${lampText}`;

    if (root) {
        root.dataset.state = ok ? 'ok' : 'bad';
    }
    lampState = activePhases.length ? 'green' : (heartbeat.ok ? 'amber' : 'red');
    if (updated) {
        updated.innerText = state && state.timestamp ? state.timestamp : '--';
    }
    if (raw) {
        raw.innerText = state && state.summary ? state.summary : '未收到有效相位状态';
    }
    if (statusText) {
        statusText.innerText = lampText;
    }
    if (realtimeText && ok) {
        realtimeText.innerText = headline;
    }
    if (light) {
        light.dataset.lamp = lampState;
    }
}

async function refreshSignalRealtimeState(fromButton = false) {
    _setSignalRealtimeStatus(false, '正在读取信号机状态...', true);
    try {
        const previousState = signalRealtimeState;
        const data = await apiGet('/api/signal/status', _getSignalRequestTimeoutMs(2000));
        signalRealtimeState = data || { ok: false };
        const nowMs = Date.now();
        const previousClock = _deriveSignalClockSnapshot(previousState, nowMs);
        const currentClock = _deriveSignalClockSnapshot(signalRealtimeState, nowMs);

        if (currentClock.hasClock && previousClock.hasClock && currentClock.stateKey === previousClock.stateKey) {
            const detail = signalRealtimeState.detail || (signalRealtimeState.detail = {});
            const mergedElapsed = Math.max(currentClock.elapsed, previousClock.liveElapsed);
            const mergedTotal = Math.max(currentClock.total, mergedElapsed);
            detail.elapsed_seconds = mergedElapsed;
            detail.total_seconds = mergedTotal;
            detail.remaining_seconds = Math.max(mergedTotal - mergedElapsed, 0);
        }

        signalRealtimeState._frontend_synced_at_ms = Date.now();
        const detail = signalRealtimeState.detail || {};
        const failureReason = signalRealtimeState.error
            || detail.error
            || (signalRealtimeState.heartbeat && signalRealtimeState.heartbeat.error)
            || '请检查控制器地址与协议响应';
        const active = Array.isArray(signalRealtimeState.active_phases) ? signalRealtimeState.active_phases : [];
        const normalizedPhase = detail.phase_index !== undefined && detail.phase_index !== null
            ? Number(detail.phase_index)
            : null;
        const phaseText = detail.phase_label
            || (Number.isFinite(normalizedPhase) ? `P${normalizedPhase}` : '')
            || (active.length ? active.join('/') : '未识别');
        const text = signalRealtimeState.ok
            ? `相位: ${phaseText}，${signalRealtimeState.summary || ''}`
            : `读取失败: ${failureReason}`;
        _setSignalRealtimeStatus(!!signalRealtimeState.ok, text, false);
        _renderSignalRealtimeState(signalRealtimeState);
        if (fromButton) {
            _pushSignalMessage('system', text);
        }
    } catch (err) {
        signalRealtimeState = { ok: false, error: err.message || '读取失败' };
        _setSignalRealtimeStatus(false, signalRealtimeState.error, false);
        _renderSignalRealtimeState(signalRealtimeState);
        if (fromButton) {
            _pushSignalMessage('system', `读取异常: ${signalRealtimeState.error}`);
        }
    } finally {
        if (_signalById('signal-panel') && _signalById('signal-panel').style.display !== 'none') {
            _startSignalRealtimeTicking();
            _scheduleSignalRealtimePolling();
        }
    }
}

function stopSignalRealtimePolling() {
    _clearSignalRealtimeTimer();
    _clearSignalRealtimeTickTimer();
}

function _renderSignalConversation() {
    const root = _signalById('signal-chat-log');
    if (!root) return;
    root.innerHTML = '';

    if (!signalConversation.length) {
        const empty = document.createElement('div');
        empty.className = 'signal-msg system';
        empty.innerText = '欢迎使用信号机控制。输入自然语言后将调用 ClawTLC NL Agent。';
        root.appendChild(empty);
        return;
    }

    signalConversation.slice(-40).forEach((item) => {
        const node = document.createElement('div');
        node.className = `signal-msg ${item.role || 'system'}`;
        node.innerText = item.content || '';
        root.appendChild(node);
    });

    root.scrollTop = root.scrollHeight;
}

function _pushSignalMessage(role, content) {
    signalConversation.push({ role, content: String(content || '') });
    if (signalConversation.length > 80) {
        signalConversation.splice(0, signalConversation.length - 80);
    }
    _renderSignalConversation();
}

function _setSignalBusy(busy) {
    signalBusy = !!busy;
    const sendBtn = _signalById('signal-send-btn');
    const sendPhaseBtn = _signalById('signal-send-phase-btn');
    if (sendBtn) {
        sendBtn.disabled = signalBusy;
        sendBtn.innerText = signalBusy ? '发送中...' : '发送控制指令';
    }
    if (sendPhaseBtn) {
        sendPhaseBtn.disabled = signalBusy;
        sendPhaseBtn.innerText = signalBusy ? '发送中...' : '发送配时请求';
    }
}

function _setSignalTimingFeedback(state, text) {
    const node = _signalById('signal-phase-send-status');
    if (!node) return;

    node.classList.remove('idle', 'pending', 'ok', 'bad');
    const normalized = ['idle', 'pending', 'ok', 'bad'].includes(state) ? state : 'idle';
    node.classList.add(normalized);
    node.innerText = String(text || '');
}

function _resolveTimingSendOutcome(result) {
    const data = result && result.data ? result.data : {};
    const response = result && result.response ? result.response : {};
    const plan = response && typeof response.plan === 'object' && response.plan ? response.plan : {};
    const planContent = String(plan.content || '').trim().toLowerCase();
    const replyText = String(response.reply || '').trim();
    const toolResult = response && typeof response.tool_result === 'object' && response.tool_result
        ? response.tool_result
        : {};

    const hasFailure = (
        data.success === false
        || planContent === 'planner_error'
        || /规划失败|planner_error/i.test(replyText)
        || toolResult.success === false
        || toolResult.ok === false
        || String(toolResult.status || '').toLowerCase() === 'error'
        || !!toolResult.error
    );

    if (hasFailure) {
        const reason = String(
            toolResult.error
            || toolResult.message
            || response.reply
            || data.message
            || '相位时间发送失败，请检查 NL Agent 日志。'
        ).trim();
        return { state: 'bad', text: `发送失败: ${reason}` };
    }

    const summary = String(
        toolResult.message
        || response.plan
        || response.reply
        || '已发送相位时间请求。'
    ).trim();
    return { state: 'ok', text: `发送成功: ${summary}` };
}

function _getSignalTimeoutSec() {
    const raw = Number(((_signalById('signal-agent-timeout') || {}).value) || 45);
    if (!Number.isFinite(raw)) return 45;
    return Math.max(1, Math.min(120, raw));
}

function _getSignalRequestTimeoutMs(extraMs = 5000) {
    const total = (_getSignalTimeoutSec() * 1000) + Number(extraMs || 0);
    return Math.max(10000, Math.min(140000, total));
}

function _getSignalSendMode() {
    const mode = String(((_signalById('signal-send-mode') || {}).value) || 'private_timing').trim().toLowerCase();
    if (mode === 'download_cmts') return 'download_cmts';
    if (mode === 'generate_cmts') return 'generate_cmts';
    return 'private_timing';
}

function _buildDownloadCmtsPhaseDurations() {
    const p1 = String(((_signalById('signal-phase-p1') || {}).value) || '').trim();
    const p2 = String(((_signalById('signal-phase-p2') || {}).value) || '').trim();
    const p3 = String(((_signalById('signal-phase-p3') || {}).value) || '').trim();
    const p6 = String(((_signalById('signal-phase-p6') || {}).value) || '').trim();
    const p7 = String(((_signalById('signal-phase-p7') || {}).value) || '').trim();
    const p8 = String(((_signalById('signal-phase-p8') || {}).value) || '').trim();
    const p4 = _deriveSignalPhaseP4();
    const missing = [];

    if (!p1) missing.push('p1');
    if (!p2) missing.push('p2');
    if (!p3) missing.push('p3');
    if (!p6) missing.push('p6');
    if (!p7) missing.push('p7');
    if (!p8) missing.push('p8');
    if (!p4) missing.push('p4');

    if (missing.length) {
        return { phase_durations: null, missing };
    }

    return {
        phase_durations: {
            1: Number(p1),
            2: Number(p2),
            3: Number(p3),
            4: Number(p4),
            5: Number(p3),
            6: Number(p6),
            7: Number(p7),
            8: Number(p8),
        },
        missing: [],
    };
}

function _buildSignalTimingPrompt() {
    const sendMode = _getSignalSendMode();
    const seq = String(((_signalById('signal-phase-seq') || {}).value) || '').trim();
    const gapMs = String(((_signalById('signal-phase-gap-ms') || {}).value) || '30').trim() || '30';
    const ackTimeout = String(((_signalById('signal-phase-ack-timeout') || {}).value) || '1.0').trim() || '1.0';
    const verifyAck = !!((_signalById('signal-phase-verify-ack') || {}).checked);

    if (sendMode === 'generate_cmts') {
        const spec = _buildGenerateCmtsSpec();
        if (spec.error) {
            return '';
        }
        const durationsText = spec.phase_durations
            ? JSON.stringify(spec.phase_durations)
            : '不覆盖（使用默认/模板中的原值）';
        const extra = [
            `template_path=${spec.template_path}`,
            spec.output_path ? `output_path=${spec.output_path}` : null,
            `phase_durations=${durationsText}`,
            `phase_semantics=${JSON.stringify(spec.phase_semantics)}`,
            `channel_map=${JSON.stringify(spec.channel_map)}`,
            spec.download_after_generate ? `download_after_generate=true` : null,
            spec.download_after_generate ? `replay_profile_path=${String(((_signalById('signal-cmts-replay-profile') || {}).value) || '').trim()}` : null,
        ].filter(Boolean).join('，');
        return [
            '请使用 generate_cmts 工具生成新的信号机方案文件。',
            spec.download_after_generate
                ? '目标是按前端编辑的相位语义和通道绑定生成新的 `.cmts`，并继续立即下发。'
                : '目标是按前端编辑的相位语义和通道绑定生成新的 `.cmts`。',
            `参数：${extra}。`,
        ].join(' ');
    }

    if (sendMode === 'download_cmts') {
        const replayProfile = String(((_signalById('signal-cmts-replay-profile') || {}).value) || '').trim();
        if (!replayProfile) {
            return '';
        }

        const phaseInfo = _buildDownloadCmtsPhaseDurations();
        const durationsText = phaseInfo.phase_durations
            ? JSON.stringify(phaseInfo.phase_durations)
            : '不覆盖（使用 replay 内原值）';

        const extra = [
            `replay_profile_path=${replayProfile}`,
            `phase_durations=${durationsText}`,
            seq ? `seq=${seq}` : null,
            `gap_ms=${gapMs}`,
            `ack_timeout=${ackTimeout}`,
            `verify_ack=${verifyAck}`,
        ].filter(Boolean).join('，');

        return [
            '请使用 download_cmts 工具执行信号机全方案下发。',
            '必须使用高风险模式并确认。',
            `参数：${extra}。`,
        ].join(' ');
    }

    const p1 = String(((_signalById('signal-phase-p1') || {}).value) || '').trim();
    const p2 = String(((_signalById('signal-phase-p2') || {}).value) || '').trim();
    const p6 = String(((_signalById('signal-phase-p6') || {}).value) || '').trim();
    const p3 = String(((_signalById('signal-phase-p3') || {}).value) || '').trim();
    if (!p1 || !p2 || !p6 || !p3) {
        return '';
    }

    const p4 = _deriveSignalPhaseP4();

    const extra = [
        `p1=${p1}`,
        `p2=${p2}`,
        `p4=${p4}`,
        `p6=${p6}`,
        `p3=${p3}`,
        seq ? `seq=${seq}` : null,
        `gap_ms=${gapMs}`,
        `ack_timeout=${ackTimeout}`,
        `verify_ack=${verifyAck}`,
    ].filter(Boolean).join('，');

    return [
        '请使用 private_timing 工具写入信号机相位时间。',
        '双环约束: Ring1(P1->P6->屏障P3) 与 Ring2(P2->P4->屏障P5) 并行运行，屏障点和起始点必须对齐。',
        `参数：${extra}。`,
        '这是高风险写操作，请先确认高风险模式并执行校验。',
    ].join(' ');
}

function _buildPhaseTimingRequest() {
    const sendMode = _getSignalSendMode();
    const rawContext = String(((_signalById('signal-phase-context') || {}).value) || '').trim();
    const objective = String(((_signalById('signal-phase-objective') || {}).value) || '').trim();
    const replayProfile = String(((_signalById('signal-cmts-replay-profile') || {}).value) || '').trim();
    const seq = String(((_signalById('signal-phase-seq') || {}).value) || '').trim();
    const gapMs = Number(((_signalById('signal-phase-gap-ms') || {}).value) || 30);
    const ackTimeout = Number(((_signalById('signal-phase-ack-timeout') || {}).value) || 1.0);
    const verifyAck = !!((_signalById('signal-phase-verify-ack') || {}).checked);
    let observations = null;

    if (rawContext) {
        try {
            observations = JSON.parse(rawContext);
        } catch (err) {
            observations = { raw: rawContext };
        }
    }

    if (sendMode === 'download_cmts') {
        const phaseInfo = _buildDownloadCmtsPhaseDurations();
        const params = {
            replay_profile_path: replayProfile,
            gap_ms: Number.isFinite(gapMs) ? gapMs : 30,
            ack_timeout: Number.isFinite(ackTimeout) ? ackTimeout : 1.0,
            verify_ack: verifyAck,
        };
        if (seq) params.seq = Number(seq);
        if (phaseInfo.phase_durations) {
            params.phase_durations = phaseInfo.phase_durations;
        }
        return {
            task: 'download_cmts',
            objective: objective || '执行全方案下发，必要时覆盖 split 相位时长',
            observations,
            params,
            constraints: {
                requires_high_risk_confirmation: true,
                replay_profile_required: true,
            },
            desired_output: {
                replay_profile_path: 'string',
                phase_durations: 'optional object {1..8 -> int}',
                seq: 'optional int',
                gap_ms: 'optional int',
                ack_timeout: 'optional float',
                verify_ack: 'optional bool',
            },
        };
    }

    if (sendMode === 'generate_cmts') {
        const spec = _buildGenerateCmtsSpec();
        if (spec.error) {
            return {
                task: 'generate_cmts',
                error: spec.error,
                params: {},
            };
        }
        const params = {
            template_path: spec.template_path,
            output_path: spec.output_path || null,
            phase_semantics: spec.phase_semantics,
            channel_map: spec.channel_map,
            strict_channels: true,
            write_seq0_ring3: false,
            auto_fill_virtual: true,
            download_after_generate: !!spec.download_after_generate,
            replay_profile_path: String(((_signalById('signal-cmts-replay-profile') || {}).value) || '').trim() || null,
            seq: seq ? Number(seq) : null,
            gap_ms: Number.isFinite(gapMs) ? gapMs : 30,
            ack_timeout: Number.isFinite(ackTimeout) ? ackTimeout : 1.0,
            verify_ack: verifyAck,
        };
        if (spec.phase_durations) {
            params.phase_durations = spec.phase_durations;
        }
        return {
            task: 'generate_cmts',
            objective: objective || '根据前端编辑的相位放行语义生成新的 cmts 方案文件',
            observations,
            params,
            constraints: {
                template_required: true,
                supports_phase_channel_binding: true,
            },
            desired_output: {
                template_path: 'string',
                output_path: 'optional string',
                phase_durations: 'optional object {1..8 -> int}',
                phase_semantics: 'object {phase -> {ring, channels[], description}}',
                channel_map: 'object {channel -> {approach, movement, type}}',
            },
        };
    }

    return {
        task: 'infer_phase_timing',
        objective: objective || '根据输入数据推理各相位时间，重点给出 p1/p2/p3/p6 四个可调相位',
        observations,
        constraints: {
            p2_plus_p4_equals_p1_plus_p6: true,
            p5_equals_p3: true,
            rings_parallel: true,
            barrier_and_start_aligned: true,
            editable_phases: ['p1', 'p2', 'p3', 'p6'],
        },
        ring_definition: {
            ring1: {
                sequence: ['p1', 'p6', 'p3'],
                sample_seconds: { p1: 20, p6: 20, p3: 20 },
            },
            ring2: {
                sequence: ['p2', 'p4', 'p5'],
                sample_seconds: { p2: 20, p4: 20, p5: 20 },
            },
        },
        desired_output: {
            p1: 'int',
            p2: 'int',
            p3: 'int',
            p4: 'int',
            p5: 'int',
            p6: 'int',
            seq: 'optional int',
            gap_ms: 'optional int',
            ack_timeout: 'optional float',
            verify_ack: 'optional bool',
        },
    };
}

function previewSignalPhaseRequest() {
    const detail = _signalById('signal-response-detail');
    if (!detail) return;

    const payload = {
        message: _buildSignalTimingPrompt(),
        phase_timing_request: _buildPhaseTimingRequest(),
    };
    detail.innerText = JSON.stringify(payload, null, 2);
}

async function _sendSignalChatMessage(message, extraPayload = {}) {
    if (!message) return;

    if (signalSettingsDirty) {
        await saveSignalSettings(true);
    }

    const payload = {
        message,
        session_id: ((_signalById('signal-session-id') || {}).value || 'traffic-console-default').trim(),
        profile: ((_signalById('signal-profile') || {}).value || 'readonly').trim(),
        high_risk_confirmed: !!((_signalById('signal-high-risk-confirmed') || {}).checked),
        ...extraPayload,
    };

    _pushSignalMessage('user', message);
    _setSignalBusy(true);

    const data = await apiPost('/api/signal/chat', payload, _getSignalRequestTimeoutMs(8000));
    const response = data && data.response ? data.response : {};
    const reply = response.reply || '已收到响应，但无 reply 字段。';

    _pushSignalMessage('assistant', reply);

    const detail = _signalById('signal-response-detail');
    if (detail) {
        detail.innerText = JSON.stringify(
            {
                session_id: response.session_id || payload.session_id,
                plan: response.plan || '',
                tool_result: response.tool_result || {},
                latency_ms: Number(data && data.latency_ms ? data.latency_ms : 0),
                raw: response,
            },
            null,
            2
        );
    }

    if (!signalHealthState || !signalHealthState.ok) {
        await refreshSignalHealth(false);
    }

    return {
        data,
        response,
        reply,
    };
}

async function saveSignalSettings(silent = false) {
    const payload = {
        signal_agent_base_url: (_signalById('signal-agent-base-url') || {}).value || '',
        signal_default_session_id: (_signalById('signal-session-id') || {}).value || '',
        signal_default_profile: (_signalById('signal-profile') || {}).value || 'readonly',
        signal_agent_timeout: Number(((_signalById('signal-agent-timeout') || {}).value) || 45),
        signal_send_mode: (_signalById('signal-send-mode') || {}).value || 'private_timing',
        signal_cmts_replay_profile: (_signalById('signal-cmts-replay-profile') || {}).value || '',
        signal_cmts_template_path: (_signalById('signal-cmts-template-path') || {}).value || '',
        signal_cmts_output_path: (_signalById('signal-cmts-output-path') || {}).value || '',
        signal_generate_download_after: !!((_signalById('signal-generate-download-after') || {}).checked),
        signal_phase_p1: (_signalById('signal-phase-p1') || {}).value || '',
        signal_phase_p2: (_signalById('signal-phase-p2') || {}).value || '',
        signal_phase_p6: (_signalById('signal-phase-p6') || {}).value || '',
        signal_phase_p3: (_signalById('signal-phase-p3') || {}).value || '',
        signal_phase_p4: _deriveSignalPhaseP4(),
        signal_phase_p7: (_signalById('signal-phase-p7') || {}).value || '',
        signal_phase_p8: (_signalById('signal-phase-p8') || {}).value || '',
        signal_phase_seq: (_signalById('signal-phase-seq') || {}).value || '',
        signal_phase_gap_ms: Number(((_signalById('signal-phase-gap-ms') || {}).value) || 30),
        signal_phase_ack_timeout: Number(((_signalById('signal-phase-ack-timeout') || {}).value) || 1.0),
        signal_phase_verify_ack: !!((_signalById('signal-phase-verify-ack') || {}).checked),
        signal_phase_context: (_signalById('signal-phase-context') || {}).value || '',
        signal_phase_objective: (_signalById('signal-phase-objective') || {}).value || '',
        signal_phase_semantics_json: (_signalById('signal-phase-semantics-json') || {}).value || '',
        signal_channel_map_json: (_signalById('signal-channel-map-json') || {}).value || '',
        signal_controller_host: (_signalById('signal-controller-host') || {}).value || '',
        signal_controller_port: Number(((_signalById('signal-controller-port') || {}).value) || 38083),
        signal_controller_timeout: Number(((_signalById('signal-controller-timeout') || {}).value) || 1.0),
        signal_controller_poll_interval: Number(((_signalById('signal-controller-poll-interval') || {}).value) || 6.0),
        signal_video_stream_url: (_signalById('signal-video-stream-url') || {}).value || '',
        signal_stream_base_url: (_signalById('signal-stream-base-url') || {}).value || '',
        signal_stream_device_id: (_signalById('signal-stream-device-id') || {}).value || '2-27',
        signal_stream_channel: Number(((_signalById('signal-stream-channel') || {}).value) || 0),
        signal_visualization_api_url: (_signalById('signal-viz-api-url') || {}).value || '',
    };

    await apiPost('/api/config', payload);
    signalSettingsDirty = false;
    if (!silent) {
        await fetchStates({ refreshSettings: settingsModalOpen });
    }

    if (!silent) {
        _pushSignalMessage('system', '信号机配置已保存。');
    }
}

async function refreshSignalHealth(fromButton = false) {
    _setSignalHealthStatus(false, '正在探测 Agent 服务...', true);
    try {
        if (signalSettingsDirty) {
            await saveSignalSettings(true);
        }

        const data = await apiGet('/api/signal/health', _getSignalRequestTimeoutMs(3000));
        signalHealthState = data || { ok: false };
        const message = signalHealthState.ok
            ? `健康检查成功(${Number(signalHealthState.latency_ms || 0)}ms): ${(signalHealthState.endpoint || '').trim()}`
            : `健康检查失败: ${signalHealthState.message || '请检查 Agent 地址与服务状态'}`;
        _setSignalHealthStatus(!!signalHealthState.ok, message, false);
        updateProgressAndMeta();

        if (fromButton) {
            _pushSignalMessage('system', message);
        }
    } catch (err) {
        signalHealthState = { ok: false, message: err.message || '健康检查失败' };
        _setSignalHealthStatus(false, signalHealthState.message, false);
        updateProgressAndMeta();
        if (fromButton) {
            _pushSignalMessage('system', `健康检查异常: ${signalHealthState.message}`);
        }
    }
}

async function sendSignalMessage() {
    const input = _signalById('signal-chat-input');
    if (!input || signalBusy) return;

    const message = String(input.value || '').trim();
    if (!message) return;

    try {
        input.value = '';
        await _sendSignalChatMessage(message);
    } catch (err) {
        _pushSignalMessage('system', `调用失败: ${err.message || err}`);
        const detail = _signalById('signal-response-detail');
        if (detail) {
            detail.innerText = JSON.stringify({ error: String(err.message || err) }, null, 2);
        }
    } finally {
        _setSignalBusy(false);
        updateProgressAndMeta();
    }
}

async function sendSignalTimingPreset() {
    const sendMode = _getSignalSendMode();
    const prompt = _buildSignalTimingPrompt();
    if (!prompt) {
        if (sendMode === 'generate_cmts') {
            const spec = _buildGenerateCmtsSpec();
            const message = spec.error || '请先补齐模板路径和方案 JSON。';
            if (!spec.error && spec.download_after_generate) {
                const replayProfile = String(((_signalById('signal-cmts-replay-profile') || {}).value) || '').trim();
                if (!replayProfile) {
                    _pushSignalMessage('system', '勾选“生成后立即下发”时，需要同时提供 Replay Profile。');
                    _setSignalTimingFeedback('bad', '发送失败: 生成后立即下发需要 replay_profile_path。');
                    return;
                }
            }
            _pushSignalMessage('system', message);
            _setSignalTimingFeedback('bad', `发送失败: ${message}`);
        } else if (sendMode === 'download_cmts') {
            _pushSignalMessage('system', '请先填写 Replay Profile；若要覆盖时长请补齐 p1 / p2 / p3 / p6 / p7 / p8。');
            _setSignalTimingFeedback('bad', '发送失败: download_cmts 需要 replay_profile_path。');
        } else {
            _pushSignalMessage('system', '请先填写 p1 / p2 / p3 / p6 再发送相位时间控制。');
            _setSignalTimingFeedback('bad', '发送失败: 请先填写 p1 / p2 / p3 / p6。');
        }
        return;
    }

    try {
        _setSignalTimingFeedback('pending', '正在发送相位时间到 NL Agent...');
        const result = await _sendSignalChatMessage(prompt, {
            phase_timing_request: _buildPhaseTimingRequest(),
        });
        const outcome = _resolveTimingSendOutcome(result);
        _setSignalTimingFeedback(outcome.state, outcome.text);
    } catch (err) {
        _pushSignalMessage('system', `调用失败: ${err.message || err}`);
        _setSignalTimingFeedback('bad', `发送失败: ${err.message || err}`);
        const detail = _signalById('signal-response-detail');
        if (detail) {
            detail.innerText = JSON.stringify({ error: String(err.message || err) }, null, 2);
        }
    } finally {
        _setSignalBusy(false);
        updateProgressAndMeta();
    }
}

function clearSignalConversation() {
    signalConversation = [];
    _renderSignalConversation();
    const detail = _signalById('signal-response-detail');
    if (detail) detail.innerText = '等待请求...';
    updateProgressAndMeta();
}

async function loadSignalConsole() {
    setSignalLayoutActive(true);
    fillSignalSettingsFromConfig();
    _renderSignalConversation();
    updateAutoSignalStreamUrl();

    if (!signalHealthState || !signalHealthState.status_code) {
        await refreshSignalHealth(false);
    } else {
        const text = signalHealthState.ok
            ? `健康检查成功: ${(signalHealthState.endpoint || '').trim()}`
            : (signalHealthState.message || '请检查 Agent 服务状态');
        _setSignalHealthStatus(!!signalHealthState.ok, text, false);
    }

    _setSignalTimingFeedback('idle', '尚未发送相位时间。');
    _renderSignalRealtimeState(signalRealtimeState || { ok: false, summary: '等待首次读取...' });
    await refreshSignalRealtimeState(false);
}
