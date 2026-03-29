function bindPipelineFormEvents() {
        if (pipelineFormBound) return;
        pipelineFormBound = true;

        const fieldIds = [
            'run-max-frames',
            'run-model',
            'run-data-dir',
            'run-bev-dir',
            'run-raw-dir',
            'run-output-dir',
            'run-use-llm',
            'run-gen-report',
        ];

        fieldIds.forEach(id => {
            const el = document.getElementById(id);
            if (!el) return;
            const eventName = (el.type === 'checkbox' || el.tagName === 'SELECT') ? 'change' : 'input';
            el.addEventListener(eventName, () => {
                pipelineFormDirty = true;
            });
        });
    }

    function fillPipelineFormDefaults() {
        if (!relationState) return;
        const cfg = relationState.config || {};
        if (pipelineFormInitialized && pipelineFormDirty) {
            return;
        }

        document.getElementById('run-data-dir').value = cfg.pipeline_data_dir || cfg.sg_dir || '';
        document.getElementById('run-bev-dir').value = cfg.pipeline_bev_dir || cfg.schematic_dir || '';
        document.getElementById('run-raw-dir').value = cfg.pipeline_raw_image_dir || cfg.img_dir || '';
        document.getElementById('run-output-dir').value = cfg.gov_outputs_dir || '';
        document.getElementById('run-max-frames').value = cfg.pipeline_max_frames || 20;
        document.getElementById('run-model').value = cfg.pipeline_model || 'qwen3-vl:4b';
        document.getElementById('run-use-llm').checked = !!cfg.pipeline_use_llm;
        document.getElementById('run-gen-report').checked = !!cfg.pipeline_generate_report;

        pipelineFormInitialized = true;
    }

    function updatePipelinePanel() {
        if (!pipelineState) return;
        const running = !!pipelineState.running;
        document.getElementById('runtime-status').innerText = running ? 'running' : 'idle';
        document.getElementById('runtime-pid').innerText = pipelineState.pid || '-';
        document.getElementById('runtime-start').innerText = pipelineState.started_at || '-';
        document.getElementById('runtime-finish').innerText = pipelineState.finished_at || '-';
        document.getElementById('runtime-exit').innerText = pipelineState.exit_code === null ? '-' : String(pipelineState.exit_code);
        document.getElementById('runtime-output').innerText = pipelineState.last_run_path || '-';
        document.getElementById('runtime-error').innerText = pipelineState.error || '-';

        const logsArr = pipelineState.logs || [];
        const logSignature = `${logsArr.length}|${logsArr.length ? logsArr[logsArr.length - 1] : ''}`;
        if (logSignature !== lastPipelineLogSignature) {
            const logs = logsArr.join('\n');
            document.getElementById('pipeline-logs').innerText = logs || '尚无日志';
            lastPipelineLogSignature = logSignature;
        }

        document.getElementById('btn-run-start').disabled = running;
        document.getElementById('btn-run-stop').disabled = !running;

        if (lastPipelineRunning && !running) {
            rebuildGovernanceIndex();
        }
        lastPipelineRunning = running;
    }

    function renderGovernanceTaskCard(data) {
        hideDone();
        currentGovernanceIndex = data.index;
        const task = data.task;
        currentFrameId = String(task.frame_id || '');
        currentFocusEntities = [];
        const slowdownLevel = String(task.slowdown_level || task.risk_level || 'low').toUpperCase();
        const slowdownScore = task.slowdown_score ?? task.risk_score ?? 0;
        const slowdownClass = task.slowdown_class_label || task.slowdown_class || 'unknown';

        setBanner(
            `Frame ${task.frame_id}`,
            `slowdown ${slowdownLevel}`,
            `score ${slowdownScore} · ${slowdownClass}`
        );
        setImages(data.img_path, data.schematic_path);
        setBevOverlayData(data.bev_overlay || null);

        const selectedRun = governanceState && governanceState.selected_run
            ? governanceState.selected_run.split(/[\\/]/).pop()
            : '-';
        document.getElementById('run-name').innerText = `运行记录: ${selectedRun}`;

        renderCauseChips(task.dominant_causes || []);
        renderSlowdownColumns(task);
        renderPedestrianSummary(task.pedestrian_crossing_summary || {});
        switchAnalysisTab(currentAnalysisTab);
        document.getElementById('governance-report').innerText = task.governance_report || '暂无治理报告';

        const llmText = (task.llm_insight || '').trim();
        const llmBox = document.getElementById('governance-llm');
        if (llmText) {
            llmBox.style.display = 'block';
            llmBox.innerText = llmText;
        } else {
            llmBox.style.display = 'none';
            llmBox.innerText = '';
        }
        document.getElementById('analysis-panel').classList.add('show');
    }

    async function jumpPedestrianFrame(direction, onlyWithData) {
        if (currentMode !== 'governance') return;
        try {
            const params = new URLSearchParams({
                direction: String(direction || 'next'),
                only_with_data: onlyWithData ? '1' : '0',
                current_index: String(currentGovernanceIndex),
            });
            const data = await apiGet(`/api/governance/pedestrian_frame?${params.toString()}`);
            if (!data.task) {
                alert(data.message || '没有可切换的行人帧。');
                return;
            }
            renderGovernanceTaskCard(data);
            switchAnalysisTab('pedestrian');
        } catch (err) {
            alert(`行人帧切换失败: ${err.message}`);
        }
    }

    async function loadGovernanceCard() {
        const data = await apiGet('/api/governance/next');
        if (!data.task) {
            showDone('治理审阅模式已全部完成。可以启动新运行后继续审阅。');
            return;
        }
        renderGovernanceTaskCard(data);
    }

    async function loadRelationCard() {
        const data = await apiGet('/api/next');
        if (!data.task) {
            showDone('关系校对模式已全部完成。');
            return;
        }

        hideDone();
        currentRelationIndex = data.index;
        currentFrameId = '';
        currentFocusEntities = [];
        setBanner(
            `${data.task.subject || '-'} (${data.task.subject_type || '-'})`,
            data.task.relation || '-',
            `${data.task.object || '-'} (${data.task.object_type || '-'})`
        );
        setImages(data.img_path, data.schematic_path);
        setBevOverlayData(null);
        clearSlowdownColumns();
        document.getElementById('analysis-panel').classList.remove('show');
    }

    async function loadCardByMode() {
        resetAllZooms();
        setActionLabels();
        if (currentMode === 'governance') {
            await loadGovernanceCard();
        } else {
            await loadRelationCard();
        }
        updateUndoButton();
    }

    function switchMode(mode) {
        currentMode = mode;
        updateModeButtons();
        applyBevRenderMode(true);
        fetchStates().then(() => loadCardByMode());
    }

    async function submitGovernance(status) {
        if (currentGovernanceIndex === -1) return;
        pushHistory(governanceHistory, currentGovernanceIndex);
        await apiPost('/api/governance/submit', { index: currentGovernanceIndex, status: status });
        await fetchStates();
        await loadCardByMode();
    }

    async function submitRelation(status) {
        if (currentRelationIndex === -1) return;
        pushHistory(relationHistory, currentRelationIndex);
        await apiPost('/api/submit', { index: currentRelationIndex, status: status });
        await fetchStates();
        await loadCardByMode();
    }

    async function handlePositive() {
        if (currentMode === 'governance') {
            if (currentAnalysisTab === 'pedestrian') {
                await jumpPedestrianFrame('next', false);
                return;
            }
            await submitGovernance('confirmed');
        } else {
            await submitRelation('correct');
        }
    }

    async function handleNegative() {
        if (currentMode === 'governance') {
            if (currentAnalysisTab === 'pedestrian') {
                await jumpPedestrianFrame('prev', true);
                return;
            }
            await submitGovernance('suspect');
        } else {
            await submitRelation('incorrect');
        }
    }

    async function handleSkip() {
        if (currentMode === 'governance') {
            if (currentAnalysisTab === 'pedestrian') {
                await jumpPedestrianFrame('next', true);
                return;
            }
            await submitGovernance('skip');
        } else {
            await submitRelation('skip');
        }
    }

    async function undoMark() {
        if (currentMode === 'governance') {
            if (governanceHistory.length === 0) return;
            const idx = governanceHistory.pop();
            await apiPost('/api/governance/submit', { index: idx, status: 'pending' });
        } else {
            if (relationHistory.length === 0) return;
            const idx = relationHistory.pop();
            await apiPost('/api/submit', { index: idx, status: 'pending' });
        }
        await fetchStates();
        await loadCardByMode();
    }

    async function rebuildGovernanceIndex() {
        await apiPost('/api/governance/rebuild', {});
        await fetchStates({ refreshSettings: settingsModalOpen });
        if (currentMode === 'governance') {
            await loadGovernanceCard();
            updateProgressAndMeta();
            updateUndoButton();
        }
    }

    async function selectLatestRun() {
        if (!governanceState || !governanceState.runs || governanceState.runs.length === 0) {
            alert('未发现运行记录。请先启动治理运行。');
            return;
        }
        const latest = governanceState.runs[0];
        await apiPost('/api/governance/select_run', { selected_run: latest.path });
        await rebuildGovernanceIndex();
    }

    async function startPipelineRun() {
        try {
            const payload = {
                max_frames: Number(document.getElementById('run-max-frames').value || 20),
                model: document.getElementById('run-model').value,
                use_llm: document.getElementById('run-use-llm').checked,
                generate_report: document.getElementById('run-gen-report').checked,
                data_dir: document.getElementById('run-data-dir').value,
                bev_dir: document.getElementById('run-bev-dir').value,
                raw_image_dir: document.getElementById('run-raw-dir').value,
                output_dir: document.getElementById('run-output-dir').value
            };
            await apiPost('/api/pipeline/start', payload);
            pipelineFormDirty = false;
            idlePollCounter = 0;
            await fetchStates();
        } catch (err) {
            alert(`启动失败: ${err.message}`);
        }
    }

    async function stopPipelineRun() {
        try {
            await apiPost('/api/pipeline/stop', {});
            await fetchStates();
        } catch (err) {
            alert(`停止失败: ${err.message}`);
        }
    }

    function fillSettingsFields() {
        if (!relationState || !governanceState) return;
        const cfg = relationState.config || {};

        document.getElementById('input-sg').value = cfg.sg_dir || '';
        document.getElementById('input-img').value = cfg.img_dir || '';
        document.getElementById('input-schem').value = cfg.schematic_dir || '';
        document.getElementById('input-gov-out').value = cfg.gov_outputs_dir || '';
        document.getElementById('input-ts-dir').value = cfg.traffic_system_dir || '';
        document.getElementById('input-pipeline-script').value = cfg.pipeline_script || '';
        document.getElementById('input-pipeline-python').value = cfg.pipeline_python || '';

        const runSelect = document.getElementById('input-run');
        runSelect.innerHTML = '';
        const runs = governanceState.runs || [];
        if (runs.length === 0) {
            const opt = document.createElement('option');
            opt.value = '';
            opt.innerText = '未找到 run_*.jsonl';
            runSelect.appendChild(opt);
        } else {
            runs.forEach(run => {
                const opt = document.createElement('option');
                opt.value = run.path;
                opt.innerText = `${run.name} (${run.mtime || '-'})`;
                if (run.path === governanceState.selected_run) opt.selected = true;
                runSelect.appendChild(opt);
            });
        }
    }

    function openSettings() {
        settingsModalOpen = true;
        fillSettingsFields();
        document.getElementById('settings-modal').classList.add('active');
    }

    function closeSettings() {
        settingsModalOpen = false;
        document.getElementById('settings-modal').classList.remove('active');
    }

    async function refreshGovernanceRuns() {
        await rebuildGovernanceIndex();
        fillSettingsFields();
    }

    async function saveSettings() {
        const payload = {
            sg_dir: document.getElementById('input-sg').value,
            img_dir: document.getElementById('input-img').value,
            schematic_dir: document.getElementById('input-schem').value,
            gov_outputs_dir: document.getElementById('input-gov-out').value,
            traffic_system_dir: document.getElementById('input-ts-dir').value,
            pipeline_script: document.getElementById('input-pipeline-script').value,
            pipeline_python: document.getElementById('input-pipeline-python').value,
            selected_run: document.getElementById('input-run').value,
            pipeline_data_dir: document.getElementById('run-data-dir').value,
            pipeline_bev_dir: document.getElementById('run-bev-dir').value,
            pipeline_raw_image_dir: document.getElementById('run-raw-dir').value,
            pipeline_model: document.getElementById('run-model').value,
            pipeline_max_frames: Number(document.getElementById('run-max-frames').value || 20),
            pipeline_use_llm: document.getElementById('run-use-llm').checked,
            pipeline_generate_report: document.getElementById('run-gen-report').checked,
        };

        await apiPost('/api/config', payload);
        pipelineFormDirty = false;
        pipelineFormInitialized = false;
        relationHistory = [];
        governanceHistory = [];
        closeSettings();
        await loadCardByMode();
    }

    function getZoomLayers(idx, wrapper) {
        if (zoomLayersCache[idx] && zoomLayersCache[idx].length) {
            return zoomLayersCache[idx];
        }
        const layers = Array.from(wrapper.querySelectorAll('.zoom-layer'));
        zoomLayersCache[idx] = layers;
        return layers;
    }

    function flushPanOrigin(idx) {
        panRafId[idx] = 0;
        const pending = panPendingOrigin[idx];
        if (!pending) return;
        const layers = zoomLayersCache[idx] || [];
        const origin = `${pending.x}% ${pending.y}%`;
        layers.forEach(layer => {
            layer.style.transformOrigin = origin;
        });
    }

    function toggleZoom(idx, event) {
        const wrapper = event.currentTarget;
        const zoomLayers = getZoomLayers(idx, wrapper);
        isZoomed[idx] = !isZoomed[idx];

        if (isZoomed[idx]) {
            wrapper.classList.add('zoomed');
            zoomLayers.forEach(layer => {
                layer.style.transition = 'transform 0.15s ease';
                layer.style.transform = 'scale(3)';
            });
            panZoom(idx, event);
            setTimeout(() => {
                if (isZoomed[idx]) {
                    zoomLayers.forEach(layer => {
                        layer.style.transition = 'none';
                    });
                }
            }, 150);
        } else {
            wrapper.classList.remove('zoomed');
            if (panRafId[idx]) {
                cancelAnimationFrame(panRafId[idx]);
                panRafId[idx] = 0;
            }
            panPendingOrigin[idx] = null;
            zoomLayers.forEach(layer => {
                layer.style.transition = 'transform 0.15s ease';
                layer.style.transform = 'scale(1)';
                layer.style.transformOrigin = 'center center';
            });
        }
    }

    function panZoom(idx, event) {
        if (!isZoomed[idx]) return;
        const wrapper = event.currentTarget;
        getZoomLayers(idx, wrapper);
        const rect = wrapper.getBoundingClientRect();
        const xPercent = ((event.clientX - rect.left) / rect.width) * 100;
        const yPercent = ((event.clientY - rect.top) / rect.height) * 100;
        panPendingOrigin[idx] = { x: xPercent, y: yPercent };
        if (!panRafId[idx]) {
            panRafId[idx] = requestAnimationFrame(() => flushPanOrigin(idx));
        }
    }

    function resetZoom(idx, event) {
        if (isZoomed[idx]) toggleZoom(idx, event);
    }

    function resetAllZooms() {
        isZoomed = [false, false];
        document.querySelectorAll('.image-wrapper').forEach(wrapper => {
            wrapper.classList.remove('zoomed');
            const idx = Number(wrapper.dataset.zoomIndex || 0);
            const layers = getZoomLayers(idx, wrapper);
            if (panRafId[idx]) {
                cancelAnimationFrame(panRafId[idx]);
                panRafId[idx] = 0;
            }
            panPendingOrigin[idx] = null;
            layers.forEach(layer => {
                layer.style.transition = 'none';
                layer.style.transform = 'scale(1)';
                layer.style.transformOrigin = 'center center';
            });
        });
    }

    function setupPolling() {
        if (pipelinePolling) {
            clearInterval(pipelinePolling);
        }
        const pollIntervalMs = uiPrefs.performanceMode === 'balanced' ? 3200 : 2500;
        pipelinePolling = setInterval(async () => {
            try {
                pipelineState = await apiGet('/api/pipeline/state');
                updatePipelinePanel();

                if (pipelineState.running) {
                    idlePollCounter = 0;
                    return;
                }

                idlePollCounter += 1;
                if (idlePollCounter >= IDLE_STATE_REFRESH_EVERY) {
                    idlePollCounter = 0;
                    await fetchStates({ refreshSettings: settingsModalOpen });
                }
            } catch (err) {
                console.warn('pipeline poll failed', err);
            }
        }, pollIntervalMs);
    }

    document.addEventListener('keydown', async (event) => {
        if (document.activeElement.tagName === 'INPUT' || document.activeElement.tagName === 'SELECT') return;
        if (event.ctrlKey || event.metaKey || event.altKey) return;

        const key = event.key.toLowerCase();
        if (key === 'y') await handlePositive();
        if (key === 'n') await handleNegative();
        if (key === 's') await handleSkip();
        if (key === 'b' || key === 'arrowleft') await undoMark();
        if (key === '1') switchMode('governance');
        if (key === '2') switchMode('relation');
    });

    window.onload = async () => {
        loadAppearancePrefs();
        syncAppearanceControls();
        bindAppearanceControls();

        document.body.classList.remove('app-ready');
        if (uiPrefs.motionEnabled) {
            requestAnimationFrame(() => {
                requestAnimationFrame(() => document.body.classList.add('app-ready'));
            });
        } else {
            document.body.classList.add('app-ready');
        }

        bindPipelineFormEvents();
        clearSlowdownColumns();
        await fetchStates({ refreshSettings: false });
        updateModeButtons();
        setupPolling();
        await loadCardByMode();
        updateBevRenderModeBadge();

        const bevImg = document.getElementById('img-schematic');
        bevImg.addEventListener('error', () => {
            if (!dynamicBevEnabled) return;
            dynamicBevEnabled = false;
            const toggle = document.getElementById('toggle-dynamic-bev');
            if (toggle) toggle.checked = false;
            applyBevRenderMode(true);
            alert('动态 BEV 渲染失败，已自动切回静态 BEV。请检查后端日志或 matplotlib 依赖。');
        });
    };

