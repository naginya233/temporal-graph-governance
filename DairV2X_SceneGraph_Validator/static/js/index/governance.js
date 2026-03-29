function updateModeButtons() {
        document.getElementById('mode-governance').classList.toggle('active', currentMode === 'governance');
        document.getElementById('mode-relation').classList.toggle('active', currentMode === 'relation');
    }

    function updateProgressAndMeta() {
        if (currentMode === 'governance') {
            const total = governanceState ? governanceState.total : 0;
            const assessed = governanceState ? governanceState.assessed : 0;
            const pending = governanceState ? governanceState.pending : 0;
            const seg = governanceState ? (governanceState.event_segments || []).length : 0;
            document.getElementById('progress-text').innerText = `治理审阅: ${assessed} / ${total} (待处理 ${pending})`;
            document.getElementById('meta-total').innerText = total;
            document.getElementById('meta-assessed').innerText = assessed;
            document.getElementById('meta-pending').innerText = pending;
            document.getElementById('meta-segments').innerText = seg;
        } else {
            const total = relationState ? relationState.total : 0;
            const assessed = relationState ? relationState.assessed : 0;
            const pending = relationState ? relationState.pending : 0;
            const seg = governanceState ? (governanceState.event_segments || []).length : 0;
            document.getElementById('progress-text').innerText = `关系校对: ${assessed} / ${total} (待处理 ${pending})`;
            document.getElementById('meta-total').innerText = total;
            document.getElementById('meta-assessed').innerText = assessed;
            document.getElementById('meta-pending').innerText = pending;
            document.getElementById('meta-segments').innerText = seg;
        }
    }

    function updateUndoButton() {
        const canUndo = currentMode === 'governance'
            ? (currentAnalysisTab !== 'pedestrian' && governanceHistory.length > 0)
            : relationHistory.length > 0;
        document.getElementById('btn-undo').disabled = !canUndo;
    }

    function setActionLabels() {
        const neg = document.getElementById('btn-negative');
        const skip = document.getElementById('btn-skip');
        const pos = document.getElementById('btn-positive');
        const panel = document.getElementById('analysis-panel');
        const pipelinePanel = document.getElementById('pipeline-panel');
        const undo = document.getElementById('btn-undo');

        if (currentMode === 'governance') {
            if (currentAnalysisTab === 'pedestrian') {
                neg.innerHTML = '上一帧有数据<span class="shortcut">(N)</span>';
                skip.innerHTML = '下一帧有数据<span class="shortcut">(S)</span>';
                pos.innerHTML = '下一帧(全部)<span class="shortcut">(Y)</span>';
                undo.disabled = true;
            } else {
                neg.innerHTML = '缓行存疑<span class="shortcut">(N)</span>';
                skip.innerHTML = '跳过<span class="shortcut">(S)</span>';
                pos.innerHTML = '确认缓行<span class="shortcut">(Y)</span>';
            }
            panel.classList.add('show');
            pipelinePanel.style.display = 'block';
        } else {
            neg.innerHTML = '错误<span class="shortcut">(N)</span>';
            skip.innerHTML = '跳过<span class="shortcut">(S)</span>';
            pos.innerHTML = '正确<span class="shortcut">(Y)</span>';
            panel.classList.remove('show');
            pipelinePanel.style.display = 'none';
        }
    }

    function setBanner(subject, relation, objectText) {
        document.getElementById('subject-info').innerText = subject || '-';
        document.getElementById('relation-info').innerText = relation || '-';
        document.getElementById('object-info').innerText = objectText || '-';
    }

    function setSchematicSrc(src, force = false) {
        const bevImg = document.getElementById('img-schematic');
        const key = String(src || '');
        if (!force && key === lastBevImagePath) return;
        bevImg.src = key;
        lastBevImagePath = key;
    }

    function updateBevRenderModeBadge() {
        const badge = document.getElementById('bev-render-mode');
        if (!badge) return;
        const isDynamic = dynamicBevEnabled && currentMode === 'governance' && !!currentFrameId;
        badge.classList.toggle('dynamic', isDynamic);
        badge.innerText = isDynamic ? '动态 BEV' : '静态 BEV';
    }

    function applyBevRenderMode(force = false) {
        const svg = document.getElementById('bev-overlay');
        const status = document.getElementById('bev-overlay-status');
        const useDynamic = dynamicBevEnabled && currentMode === 'governance' && !!currentFrameId;

        updateBevRenderModeBadge();

        // 静态模式不再展示叠加高亮框，动态模式也由后端重渲染直接输出高亮。
        if (svg) {
            svg.style.display = 'none';
            if (!useDynamic) svg.innerHTML = '';
        }
        if (status) status.style.display = 'none';

        if (useDynamic) {
            const entityKey = currentFocusEntities.join(',');
            const signature = `${currentFrameId}|${entityKey}`;
            if (force || signature !== lastDynamicSignature) {
                const timestamp = Date.now();
                const src = `/api/governance/render_bev?frame_id=${encodeURIComponent(currentFrameId)}&entities=${encodeURIComponent(entityKey)}&t=${timestamp}`;
                setSchematicSrc(src, true);
                lastDynamicSignature = signature;
            }
            return;
        }

        lastDynamicSignature = '';
        if (staticBevPath) {
            const timestamp = Date.now();
            setSchematicSrc(`/api/image?path=${encodeURIComponent(staticBevPath)}&t=${timestamp}`, force);
        } else {
            setSchematicSrc('', force);
        }
    }

    function onDynamicBevToggle(enabled) {
        dynamicBevEnabled = !!enabled;
        applyBevRenderMode(true);
    }

    function setImages(rawPath, bevPath) {
        const rawImg = document.getElementById('img-original');

        if (rawPath !== lastRawImagePath) {
            const timestamp = Date.now();
            rawImg.src = rawPath ? `/api/image?path=${encodeURIComponent(rawPath)}&t=${timestamp}` : '';
            lastRawImagePath = rawPath || '';
        }

        staticBevPath = bevPath || '';
        applyBevRenderMode(false);
    }

    function showDone(text) {
        document.getElementById('done-view').classList.add('show');
        document.getElementById('done-text').innerText = text;
        document.getElementById('workspace').style.display = 'none';
        document.getElementById('action-bar').style.display = 'none';
        document.getElementById('analysis-panel').classList.remove('show');
        setBanner('已完成', 'DONE', '暂无待处理项');
    }

    function hideDone() {
        document.getElementById('done-view').classList.remove('show');
        document.getElementById('workspace').style.display = 'grid';
        document.getElementById('action-bar').style.display = 'flex';
    }

    function renderCauseChips(causes) {
        const wrap = document.getElementById('cause-chips');
        wrap.innerHTML = '';
        const list = causes && causes.length ? causes : ['no-dominant-cause'];
        list.forEach(item => {
            const span = document.createElement('span');
            span.className = 'chip';
            span.innerText = item;
            wrap.appendChild(span);
        });
    }

    function clearSlowdownColumns() {
        document.getElementById('flow-objects-list').innerHTML = '<div class="flow-empty">暂无对象</div>';
        document.getElementById('flow-individuals-list').innerHTML = '<div class="flow-empty">暂无个体</div>';
        document.getElementById('flow-sources-list').innerHTML = '<div class="flow-empty">暂无源头</div>';
        document.getElementById('flow-link-hint').innerText = '点击任一对象/个体/源头可联动高亮，再次点击取消。';
        document.getElementById('flow-objects-title').innerText = '车辆缓行对象';
        document.getElementById('flow-individuals-title').innerText = '车辆个体';
        document.getElementById('flow-sources-title').innerText = '车辆源头';
        currentFocusEntities = [];
        renderBevEntityOverlay([]);
        slowdownLinkSelection = null;
        slowdownLinkContext = null;
        clearPedestrianPanel();
        switchAnalysisTab('vehicle');
    }

    function updateAnalysisTabButtons() {
        const tabVehicle = document.getElementById('tab-vehicle');
        const tabPedestrian = document.getElementById('tab-pedestrian');
        if (tabVehicle) tabVehicle.classList.toggle('active', currentAnalysisTab === 'vehicle');
        if (tabPedestrian) tabPedestrian.classList.toggle('active', currentAnalysisTab === 'pedestrian');
    }

    function switchAnalysisTab(tab) {
        currentAnalysisTab = tab === 'pedestrian' ? 'pedestrian' : 'vehicle';
        updateAnalysisTabButtons();

        const vehiclePanel = document.getElementById('vehicle-analysis-panel');
        const pedestrianPanel = document.getElementById('pedestrian-analysis-panel');
        if (!vehiclePanel || !pedestrianPanel) return;

        const pedestrianMode = currentAnalysisTab === 'pedestrian';
        vehiclePanel.style.display = pedestrianMode ? 'none' : 'block';
        pedestrianPanel.style.display = pedestrianMode ? 'block' : 'none';

        if (!pedestrianMode && slowdownLinkContext) {
            renderSlowdownColumnsFromContext();
        }

        if (pedestrianMode && currentMode === 'governance') {
            const summary = pedestrianCrossingSummary || {};
            const hasPedData =
                Number(summary.crossing_event_count || 0) > 0 ||
                Number(summary.crossing_edge_count || 0) > 0 ||
                Number(summary.active_crossing_count || 0) > 0;
            if (!hasPedData && currentGovernanceIndex !== -1) {
                document.getElementById('ped-insight').innerText = '当前帧无行人过街数据，正在定位下一帧有数据样本...';
                jumpPedestrianFrame('next', true);
            }
        }

        setActionLabels();
        updateUndoButton();
    }

    function _pedLevelText(level) {
        const value = String(level || '').toLowerCase();
        if (value === 'saturated') return '饱和过街';
        if (value === 'busy') return '繁忙过街';
        return '正常过街';
    }

    function clearPedestrianPanel() {
        pedestrianCrossingSummary = null;
        pedestrianSelectedEntity = '';
        const pedConfig = governanceState && governanceState.pedestrian_config ? governanceState.pedestrian_config : {};
        setPedestrianWindowControls(
            Number(pedConfig.window_frames || pedestrianWindowFrames),
            Number(pedConfig.busy_threshold || pedestrianBusyThreshold),
            Number(pedConfig.saturated_threshold || pedestrianSaturatedThreshold)
        );
        document.getElementById('ped-level').innerText = '-';
        document.getElementById('ped-events').innerText = '0';
        document.getElementById('ped-unique').innerText = '0';
        document.getElementById('ped-active').innerText = '0';
        document.getElementById('ped-active-entities').innerHTML = '<div class="flow-empty">暂无当前过街行人</div>';
        document.getElementById('ped-new-entities').innerHTML = '<div class="flow-empty">暂无新触发行人</div>';
        document.getElementById('ped-targets').innerHTML = '<div class="flow-empty">暂无过街目标</div>';
        document.getElementById('ped-insight').innerText = '暂无行人过街统计。';
        document.getElementById('tab-vehicle').innerText = '车辆缓行';
        document.getElementById('tab-pedestrian').innerText = '行人过街';
    }

    function setPedestrianWindowControls(frames, busyThreshold = pedestrianBusyThreshold, saturatedThreshold = pedestrianSaturatedThreshold) {
        const normalized = Math.max(5, Math.min(5000, Number(frames || 60)));
        const normalizedBusy = Math.max(1, Math.min(5000, Number(busyThreshold || 8)));
        const normalizedSaturated = Math.max(normalizedBusy + 1, Math.min(10000, Number(saturatedThreshold || 14)));

        pedestrianWindowFrames = normalized;
        pedestrianBusyThreshold = normalizedBusy;
        pedestrianSaturatedThreshold = normalizedSaturated;

        const slider = document.getElementById('ped-window-slider');
        const input = document.getElementById('ped-window-input');
        const label = document.getElementById('ped-window-value');
        const busyInput = document.getElementById('ped-busy-input');
        const saturatedInput = document.getElementById('ped-saturated-input');

        if (slider) {
            const sliderMax = 300;
            slider.value = String(Math.max(5, Math.min(sliderMax, normalized)));
        }
        if (input) input.value = String(normalized);
        if (label) label.innerText = String(normalized);
        if (busyInput) busyInput.value = String(normalizedBusy);
        if (saturatedInput) {
            saturatedInput.min = String(normalizedBusy + 1);
            saturatedInput.value = String(normalizedSaturated);
        }
    }

    function onPedestrianWindowRangeInput(value) {
        const v = Math.max(5, Math.min(5000, Number(value || 60)));
        const label = document.getElementById('ped-window-value');
        const input = document.getElementById('ped-window-input');
        if (label) label.innerText = String(v);
        if (input) input.value = String(v);
    }

    async function applyPedestrianWindowFrames(value, options = {}) {
        const frames = Math.max(5, Math.min(5000, Number(value || 60)));
        const busy = Math.max(1, Math.min(5000, Number(options.busyThreshold ?? pedestrianBusyThreshold)));
        const saturated = Math.max(busy + 1, Math.min(10000, Number(options.saturatedThreshold ?? pedestrianSaturatedThreshold)));

        if (!Number.isFinite(frames)) return;
        if (!Number.isFinite(busy) || !Number.isFinite(saturated)) return;
        if (frames === pedestrianWindowFrames && busy === pedestrianBusyThreshold && saturated === pedestrianSaturatedThreshold) return;

        const previousWindow = pedestrianWindowFrames;
        const previousBusy = pedestrianBusyThreshold;
        const previousSaturated = pedestrianSaturatedThreshold;

        try {
            const updated = await apiPost('/api/governance/pedestrian_window', {
                window_frames: frames,
                busy_threshold: busy,
                saturated_threshold: saturated,
            });

            setPedestrianWindowControls(
                Number(updated.window_frames || frames),
                Number(updated.busy_threshold || busy),
                Number(updated.saturated_threshold || saturated)
            );
            await fetchStates();

            if (currentMode === 'governance' && currentFrameId) {
                const data = await apiGet(`/api/governance/frame?frame_id=${encodeURIComponent(currentFrameId)}`);
                if (data && data.task) {
                    renderGovernanceTaskCard(data);
                    switchAnalysisTab('pedestrian');
                    return;
                }
            }
            await loadCardByMode();
        } catch (err) {
            alert(`更新行人窗口失败: ${err.message}`);
            setPedestrianWindowControls(previousWindow, previousBusy, previousSaturated);
        }
    }

    async function onPedestrianWindowRangeChange(value) {
        await applyPedestrianWindowFrames(value);
    }

    async function onPedestrianWindowNumberChange(value) {
        const frames = Math.max(5, Math.min(5000, Number(value || 60)));
        await applyPedestrianWindowFrames(frames);
    }

    async function onPedestrianBusyThresholdChange(value) {
        await applyPedestrianWindowFrames(pedestrianWindowFrames, {
            busyThreshold: Number(value || pedestrianBusyThreshold),
            saturatedThreshold: pedestrianSaturatedThreshold,
        });
    }

    async function onPedestrianSaturatedThresholdChange(value) {
        await applyPedestrianWindowFrames(pedestrianWindowFrames, {
            busyThreshold: pedestrianBusyThreshold,
            saturatedThreshold: Number(value || pedestrianSaturatedThreshold),
        });
    }

    function togglePedestrianEntity(entity) {
        const key = String(entity || '').trim();
        if (!key) return;
        pedestrianSelectedEntity = pedestrianSelectedEntity === key ? '' : key;
        renderPedestrianSummary(pedestrianCrossingSummary || {});
        const focus = pedestrianSelectedEntity ? [pedestrianSelectedEntity] : [];
        renderBevEntityOverlay(focus);
    }

    function renderPedestrianEntityList(rootId, items, emptyText, clickable = false) {
        const root = document.getElementById(rootId);
        if (!root) return;
        root.innerHTML = '';

        const values = Array.isArray(items) ? items.map(v => String(v).trim()).filter(Boolean) : [];
        if (values.length === 0) {
            root.innerHTML = `<div class="flow-empty">${emptyText}</div>`;
            return;
        }

        values.forEach((value, idx) => {
            const div = document.createElement('div');
            const activeClass = clickable && pedestrianSelectedEntity === value ? ' active' : '';
            div.className = `flow-item${clickable ? ' clickable' : ''}${activeClass}`;
            div.innerHTML = `<strong>${idx + 1}.</strong> ${value}`;
            if (clickable) {
                div.onclick = () => togglePedestrianEntity(value);
            }
            root.appendChild(div);
        });
    }

    function renderPedestrianSummary(summary) {
        const data = summary && typeof summary === 'object' ? summary : {};
        const thresholds = data.thresholds && typeof data.thresholds === 'object' ? data.thresholds : {};
        pedestrianCrossingSummary = data;
        setPedestrianWindowControls(
            Number(data.window_frames || pedestrianWindowFrames),
            Number(thresholds.busy || pedestrianBusyThreshold),
            Number(thresholds.saturated || pedestrianSaturatedThreshold)
        );

        const events = Number(data.crossing_event_count || 0);
        const uniqueActive = Number(data.unique_active_pedestrian_count || 0);
        const activeNow = Number(data.active_crossing_count || 0);
        const level = _pedLevelText(data.saturation_level);

        document.getElementById('ped-level').innerText = level;
        document.getElementById('ped-events').innerText = String(events);
        document.getElementById('ped-unique').innerText = String(uniqueActive);
        document.getElementById('ped-active').innerText = String(activeNow);

        renderPedestrianEntityList('ped-active-entities', data.active_entities, '暂无当前过街行人', true);
        renderPedestrianEntityList('ped-new-entities', data.new_crossing_entities, '暂无新触发行人', true);
        renderPedestrianEntityList('ped-targets', data.active_targets, '暂无过街目标', false);

        const insight = String(data.insight || '暂无行人过街统计。').trim();
        document.getElementById('ped-insight').innerText = insight || '暂无行人过街统计。';
        document.getElementById('tab-pedestrian').innerText = `行人过街 (${events})`;
        document.getElementById('tab-vehicle').innerText = '车辆缓行';
    }

    function _createSvgEl(name) {
        return document.createElementNS('http://www.w3.org/2000/svg', name);
    }

    function setBevOverlayData(data) {
        if (data && typeof data === 'object') {
            currentBevOverlay = data;
        } else {
            currentBevOverlay = null;
        }
        renderBevEntityOverlay([]);
    }

    function renderBevEntityOverlay(entityIds) {
        const svg = document.getElementById('bev-overlay');
        const status = document.getElementById('bev-overlay-status');
        if (!svg || !status) return;

        svg.innerHTML = '';

        const validIds = Array.from(new Set((entityIds || []).map(v => String(v))));
        currentFocusEntities = validIds;
        if (!dynamicBevEnabled || currentMode !== 'governance') {
            status.style.display = 'none';
            svg.style.display = 'none';
            return;
        }
        if (dynamicBevEnabled && currentMode === 'governance') {
            applyBevRenderMode(false);
        }
        const noSelectionText = currentMode === 'governance' ? '未选择车流对象' : '关系模式不显示高亮';

        if (!currentBevOverlay || currentMode !== 'governance') {
            status.innerText = noSelectionText;
            return;
        }

        const bounds = currentBevOverlay.world_bounds || {};
        const minX = Number(bounds.min_x);
        const maxX = Number(bounds.max_x);
        const minY = Number(bounds.min_y);
        const maxY = Number(bounds.max_y);
        const spanX = maxX - minX;
        const spanY = maxY - minY;

        if (!(Number.isFinite(spanX) && spanX > 0 && Number.isFinite(spanY) && spanY > 0)) {
            status.innerText = '缺少世界坐标范围';
            return;
        }

        if (validIds.length === 0) {
            status.innerText = '选择 flow / 个体 / 源头后显示 BEV 高亮';
            return;
        }

        const entityPolygons = currentBevOverlay.entity_polygons || {};
        let renderCount = 0;

        validIds.forEach((entityId, idx) => {
            const polygons = entityPolygons[entityId];
            if (!Array.isArray(polygons) || polygons.length === 0) return;

            const hue = (idx * 67) % 360;
            const strokeColor = `hsl(${hue} 95% 42%)`;
            const fillColor = `hsla(${hue} 95% 55% / 0.18)`;

            polygons.forEach((poly) => {
                if (!Array.isArray(poly) || poly.length < 3) return;
                const projected = poly
                    .filter(pt => Array.isArray(pt) && pt.length >= 2)
                    .map(pt => {
                        const x = Number(pt[0]);
                        const y = Number(pt[1]);
                        const nx = ((x - minX) / spanX) * 1000;
                        const ny = 1000 - ((y - minY) / spanY) * 1000;
                        return [nx, ny];
                    })
                    .filter(pt => Number.isFinite(pt[0]) && Number.isFinite(pt[1]));

                if (projected.length < 3) return;

                const polygonEl = _createSvgEl('polygon');
                polygonEl.setAttribute('points', projected.map(pt => `${pt[0].toFixed(1)},${pt[1].toFixed(1)}`).join(' '));
                polygonEl.setAttribute('fill', fillColor);
                polygonEl.setAttribute('stroke', strokeColor);
                polygonEl.setAttribute('stroke-width', '2.4');
                polygonEl.setAttribute('vector-effect', 'non-scaling-stroke');
                svg.appendChild(polygonEl);

                renderCount += 1;
            });

            const firstPoly = polygons[0];
            if (Array.isArray(firstPoly) && firstPoly.length > 0) {
                const pts = firstPoly
                    .filter(pt => Array.isArray(pt) && pt.length >= 2)
                    .map(pt => [Number(pt[0]), Number(pt[1])])
                    .filter(pt => Number.isFinite(pt[0]) && Number.isFinite(pt[1]));
                if (pts.length > 0) {
                    const cxWorld = pts.reduce((acc, pt) => acc + pt[0], 0) / pts.length;
                    const cyWorld = pts.reduce((acc, pt) => acc + pt[1], 0) / pts.length;
                    const cx = ((cxWorld - minX) / spanX) * 1000;
                    const cy = 1000 - ((cyWorld - minY) / spanY) * 1000;
                    const labelBg = _createSvgEl('rect');
                    labelBg.setAttribute('x', String(cx - 20));
                    labelBg.setAttribute('y', String(cy - 16));
                    labelBg.setAttribute('width', '40');
                    labelBg.setAttribute('height', '14');
                    labelBg.setAttribute('rx', '4');
                    labelBg.setAttribute('fill', 'rgba(2,6,23,0.72)');
                    svg.appendChild(labelBg);

                    const label = _createSvgEl('text');
                    label.setAttribute('x', String(cx));
                    label.setAttribute('y', String(cy - 6));
                    label.setAttribute('text-anchor', 'middle');
                    label.setAttribute('fill', '#fff');
                    label.setAttribute('font-size', '10');
                    label.setAttribute('font-weight', '700');
                    label.textContent = entityId;
                    svg.appendChild(label);
                }
            }
        });

        if (renderCount === 0) {
            status.innerText = '未匹配到可叠加对象';
            return;
        }
        status.innerText = `已高亮 ${validIds.length} 个对象`;
    }

    function renderList(elId, items, formatter, maxItems, emptyText) {
        const root = document.getElementById(elId);
        root.innerHTML = '';

        if (!Array.isArray(items) || items.length === 0) {
            root.innerHTML = `<div class="flow-empty">${emptyText}</div>`;
            return;
        }

        const clipped = items.slice(0, maxItems);
        clipped.forEach((item, idx) => {
            const div = document.createElement('div');
            div.className = 'flow-item';
            div.innerHTML = formatter(item, idx);
            root.appendChild(div);
        });

        if (items.length > maxItems) {
            const tail = document.createElement('div');
            tail.className = 'flow-empty';
            tail.innerText = `其余 ${items.length - maxItems} 项已折叠`; 
            root.appendChild(tail);
        }
    }

    function buildSlowdownLinkContext(task) {
        const objects = Array.isArray(task.slowdown_objects) ? task.slowdown_objects : [];
        const individualEntities = Array.isArray(task.slowdown_individual_entities) ? task.slowdown_individual_entities : [];
        const sourceEntities = Array.isArray(task.slowdown_source_entities) ? task.slowdown_source_entities : [];
        const sourceSummary = task.slowdown_source_summary || {};

        const objectById = new Map();
        const individualToObjectIds = new Map();
        const sourceToObjectIds = new Map();

        objects.forEach((obj, idx) => {
            const flowId = String(obj.flow_id || `flow_${idx + 1}`);
            objectById.set(flowId, obj);

            const members = Array.isArray(obj.individual_entities) ? obj.individual_entities.map(v => String(v)) : [];
            const sources = Array.isArray(obj.source_entities) ? obj.source_entities.map(v => String(v)) : [];

            members.forEach(entity => {
                if (!individualToObjectIds.has(entity)) individualToObjectIds.set(entity, new Set());
                individualToObjectIds.get(entity).add(flowId);
            });

            sources.forEach(source => {
                if (!sourceToObjectIds.has(source)) sourceToObjectIds.set(source, new Set());
                sourceToObjectIds.get(source).add(flowId);
            });
        });

        const sourceCards = sourceEntities.map((entity) => {
            const text = String(entity);
            const mergeList = Array.isArray(sourceSummary.merge_bottleneck_sources) ? sourceSummary.merge_bottleneck_sources : [];
            const cycleList = Array.isArray(sourceSummary.cycle_lock_sources) ? sourceSummary.cycle_lock_sources : [];
            const headList = Array.isArray(sourceSummary.queue_head_sources) ? sourceSummary.queue_head_sources : [];
            let sourceType = 'queue_head';
            if (mergeList.includes(text)) sourceType = 'merge_bottleneck';
            else if (cycleList.includes(text)) sourceType = 'cycle_lock';
            else if (headList.includes(text)) sourceType = 'queue_head';
            return { entity: text, sourceType };
        });

        return {
            objects,
            individualEntities: individualEntities.map(v => String(v)),
            sourceCards,
            objectById,
            individualToObjectIds,
            sourceToObjectIds,
        };
    }

    function resolveLinkedSets(context, selection) {
        if (!selection || !context) {
            return {
                objectIds: new Set(),
                individuals: new Set(),
                sources: new Set(),
            };
        }

        const objectIds = new Set();
        const individuals = new Set();
        const sources = new Set();

        if (selection.type === 'object') {
            objectIds.add(selection.value);
        } else if (selection.type === 'individual') {
            (context.individualToObjectIds.get(selection.value) || new Set()).forEach(id => objectIds.add(id));
        } else if (selection.type === 'source') {
            (context.sourceToObjectIds.get(selection.value) || new Set()).forEach(id => objectIds.add(id));
        }

        objectIds.forEach(id => {
            const obj = context.objectById.get(id);
            if (!obj) return;

            const members = Array.isArray(obj.individual_entities) ? obj.individual_entities : [];
            const sourceList = Array.isArray(obj.source_entities) ? obj.source_entities : [];
            members.forEach(entity => individuals.add(String(entity)));
            sourceList.forEach(entity => sources.add(String(entity)));
        });

        if (selection.type === 'individual') individuals.add(selection.value);
        if (selection.type === 'source') sources.add(selection.value);

        return { objectIds, individuals, sources };
    }

    function updateFlowLinkHint(selection) {
        const hint = document.getElementById('flow-link-hint');
        if (!selection) {
            hint.innerText = '点击任一对象/个体/源头可联动高亮，再次点击取消。';
            return;
        }
        const labelMap = {
            object: '车流对象',
            individual: '个体',
            source: '源头',
        };
        hint.innerText = `已联动：${labelMap[selection.type] || selection.type} = ${selection.value}`;
    }

    function toggleSlowdownLink(type, value) {
        const key = String(value);
        if (slowdownLinkSelection && slowdownLinkSelection.type === type && slowdownLinkSelection.value === key) {
            slowdownLinkSelection = null;
        } else {
            slowdownLinkSelection = { type, value: key };
        }
        if (slowdownLinkContext) {
            renderSlowdownColumnsFromContext();
        }
    }

    function createFlowItem(html, classes, onClick) {
        const div = document.createElement('div');
        div.className = `flow-item clickable ${classes.join(' ')}`.trim();
        div.innerHTML = html;
        div.onclick = onClick;
        return div;
    }

    function renderSlowdownColumnsFromContext() {
        if (!slowdownLinkContext) {
            clearSlowdownColumns();
            return;
        }

        const objectsRoot = document.getElementById('flow-objects-list');
        const individualsRoot = document.getElementById('flow-individuals-list');
        const sourcesRoot = document.getElementById('flow-sources-list');

        objectsRoot.innerHTML = '';
        individualsRoot.innerHTML = '';
        sourcesRoot.innerHTML = '';

        const context = slowdownLinkContext;
        const linked = resolveLinkedSets(context, slowdownLinkSelection);
        const hasSelection = !!slowdownLinkSelection;

        const objectList = context.objects.slice(0, MAX_OBJECT_RENDER);
        if (objectList.length === 0) {
            objectsRoot.innerHTML = '<div class="flow-empty">暂无车流对象</div>';
        } else {
            objectList.forEach((obj, idx) => {
                const flowId = String(obj.flow_id || `flow_${idx + 1}`);
                const kind = obj.flow_kind || '-';
                const members = Array.isArray(obj.individual_entities) ? obj.individual_entities.join(', ') : '-';
                const sources = Array.isArray(obj.source_entities) ? obj.source_entities.join(', ') : '-';

                const isActive = slowdownLinkSelection && slowdownLinkSelection.type === 'object' && slowdownLinkSelection.value === flowId;
                const isRelated = linked.objectIds.has(flowId);
                const classes = [];
                if (isActive) classes.push('active');
                else if (hasSelection && isRelated) classes.push('related');
                else if (hasSelection) classes.push('muted');

                objectsRoot.appendChild(
                    createFlowItem(
                        `<strong>${flowId}</strong> (${kind})<br>个体: ${members}<br>源头: ${sources}`,
                        classes,
                        () => toggleSlowdownLink('object', flowId)
                    )
                );
            });
            if (context.objects.length > MAX_OBJECT_RENDER) {
                const tail = document.createElement('div');
                tail.className = 'flow-empty';
                tail.innerText = `其余 ${context.objects.length - MAX_OBJECT_RENDER} 项已折叠`;
                objectsRoot.appendChild(tail);
            }
        }

        const individualList = context.individualEntities.slice(0, MAX_ENTITY_RENDER);
        if (individualList.length === 0) {
            individualsRoot.innerHTML = '<div class="flow-empty">暂无个体</div>';
        } else {
            individualList.forEach((entity, idx) => {
                const isActive = slowdownLinkSelection && slowdownLinkSelection.type === 'individual' && slowdownLinkSelection.value === entity;
                const isRelated = linked.individuals.has(entity);
                const classes = [];
                if (isActive) classes.push('active');
                else if (hasSelection && isRelated) classes.push('related');
                else if (hasSelection) classes.push('muted');

                individualsRoot.appendChild(
                    createFlowItem(
                        `<strong>${idx + 1}.</strong> ${entity}`,
                        classes,
                        () => toggleSlowdownLink('individual', entity)
                    )
                );
            });
            if (context.individualEntities.length > MAX_ENTITY_RENDER) {
                const tail = document.createElement('div');
                tail.className = 'flow-empty';
                tail.innerText = `其余 ${context.individualEntities.length - MAX_ENTITY_RENDER} 项已折叠`;
                individualsRoot.appendChild(tail);
            }
        }

        const sourceList = context.sourceCards.slice(0, MAX_ENTITY_RENDER);
        if (sourceList.length === 0) {
            sourcesRoot.innerHTML = '<div class="flow-empty">暂无源头</div>';
        } else {
            sourceList.forEach((item, idx) => {
                const sourceEntity = String(item.entity);
                const isActive = slowdownLinkSelection && slowdownLinkSelection.type === 'source' && slowdownLinkSelection.value === sourceEntity;
                const isRelated = linked.sources.has(sourceEntity);
                const classes = [];
                if (isActive) classes.push('active');
                else if (hasSelection && isRelated) classes.push('related');
                else if (hasSelection) classes.push('muted');

                sourcesRoot.appendChild(
                    createFlowItem(
                        `<strong>${idx + 1}.</strong> ${sourceEntity}<br>类型: ${item.sourceType}`,
                        classes,
                        () => toggleSlowdownLink('source', sourceEntity)
                    )
                );
            });
            if (context.sourceCards.length > MAX_ENTITY_RENDER) {
                const tail = document.createElement('div');
                tail.className = 'flow-empty';
                tail.innerText = `其余 ${context.sourceCards.length - MAX_ENTITY_RENDER} 项已折叠`;
                sourcesRoot.appendChild(tail);
            }
        }

        const focusEntities = hasSelection ? Array.from(linked.individuals) : [];
        renderBevEntityOverlay(focusEntities);
        updateFlowLinkHint(slowdownLinkSelection);
    }

    function renderSlowdownColumns(task) {
        slowdownLinkContext = buildSlowdownLinkContext(task);
        slowdownLinkSelection = null;
        renderSlowdownColumnsFromContext();
    }

    async function fetchStates(options = {}) {
        const refreshSettings = !!options.refreshSettings;

        const [rState, gState, pState] = await Promise.all([
            apiGet('/api/state'),
            apiGet('/api/governance/state'),
            apiGet('/api/pipeline/state')
        ]);
        relationState = rState;
        governanceState = gState;
        pipelineState = pState;

        if (governanceState && governanceState.pedestrian_config) {
            setPedestrianWindowControls(
                Number(governanceState.pedestrian_config.window_frames || pedestrianWindowFrames),
                Number(governanceState.pedestrian_config.busy_threshold || pedestrianBusyThreshold),
                Number(governanceState.pedestrian_config.saturated_threshold || pedestrianSaturatedThreshold)
            );
        }

        if (refreshSettings || settingsModalOpen) {
            fillSettingsFields();
        }
        fillPipelineFormDefaults();
        updateProgressAndMeta();
        updateUndoButton();
        updatePipelinePanel();
    }

    function pushHistory(history, value) {
        history.push(value);
        if (history.length > HISTORY_LIMIT) {
            history.splice(0, history.length - HISTORY_LIMIT);
        }
    }

    

