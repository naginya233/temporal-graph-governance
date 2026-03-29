    const UI_PREFS_KEY = "dair_console_ui_prefs_v1";

    function normalizeShowcasePrefs(raw) {
        const source = raw && typeof raw === "object" ? raw : {};
        const themeRaw = String(source.theme || "system").toLowerCase();
        const performanceRaw = String(source.performanceMode || "balanced").toLowerCase();
        const fontScaleRaw = Number(source.fontScale || 100);

        return {
            theme: ["system", "light", "dark"].includes(themeRaw) ? themeRaw : "system",
            performanceMode: performanceRaw === "rich" ? "rich" : "balanced",
            fontScale: Math.max(90, Math.min(115, Number.isFinite(fontScaleRaw) ? fontScaleRaw : 100)),
        };
    }

    function resolveTheme(theme) {
        if (theme === "light" || theme === "dark") return theme;
        return window.matchMedia && window.matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light";
    }

    function loadShowcasePrefs() {
        try {
            const text = localStorage.getItem(UI_PREFS_KEY);
            if (!text) return normalizeShowcasePrefs({});
            return normalizeShowcasePrefs(JSON.parse(text));
        } catch (err) {
            console.warn("showcase prefs load failed", err);
            return normalizeShowcasePrefs({});
        }
    }

    function saveShowcasePrefs(prefs) {
        try {
            localStorage.setItem(UI_PREFS_KEY, JSON.stringify(prefs));
        } catch (err) {
            console.warn("showcase prefs save failed", err);
        }
    }

    function updateUiStateBadge(prefs) {
        const badge = document.getElementById("showcase-ui-state");
        if (!badge) return;
        const activeTheme = resolveTheme(prefs.theme);
        badge.textContent = `UI: ${activeTheme}/${prefs.performanceMode}`;
    }

    function applyShowcaseAppearance(prefs) {
        const root = document.documentElement;
        root.setAttribute("data-theme", resolveTheme(prefs.theme));
        root.setAttribute("data-performance", prefs.performanceMode);
        root.style.fontSize = `${prefs.fontScale}%`;
        updateUiStateBadge(prefs);
    }

    function bindShowcaseAppearance() {
        const prefs = loadShowcasePrefs();
        applyShowcaseAppearance(prefs);

        const toggleBtn = document.getElementById("toggle-theme-btn");
        if (toggleBtn) {
            toggleBtn.addEventListener("click", () => {
                const nextTheme = prefs.theme === "system" ? "light" : (prefs.theme === "light" ? "dark" : "system");
                prefs.theme = nextTheme;
                saveShowcasePrefs(prefs);
                applyShowcaseAppearance(prefs);
            });
        }

        if (window.matchMedia) {
            const media = window.matchMedia("(prefers-color-scheme: dark)");
            const listener = () => {
                if (prefs.theme === "system") {
                    applyShowcaseAppearance(prefs);
                }
            };
            if (typeof media.addEventListener === "function") {
                media.addEventListener("change", listener);
            } else if (typeof media.addListener === "function") {
                media.addListener(listener);
            }
        }
    }

    function fmtNumber(value) {
        const n = Number(value || 0);
        if (!Number.isFinite(n)) return "0";
        return n.toLocaleString();
    }

    function levelLabel(key) {
        if (key === "high") return "High";
        if (key === "medium") return "Medium";
        if (key === "low") return "Low";
        return key;
    }

    function classLabel(key) {
        const map = {
            normal_controlled_queue: "Normal Controlled",
            sustained_slowdown: "Sustained Slowdown",
            anomalous_slowdown: "Anomalous Slowdown"
        };
        return map[key] || key;
    }

    function isTruckType(text) {
        const t = String(text || "").toUpperCase();
        return t.includes("TRUCK") || t.includes("FREIGHT") || t.includes("CARGO");
    }

    function isNonMotorType(text) {
        const t = String(text || "").toUpperCase();
        return t.includes("BICYCLE") || t.includes("CYCLIST") || t.includes("TRICYCLE") || t.includes("PERSON") || t.includes("PEDESTRIAN");
    }

    function renderBars(rootId, entries, colorResolver) {
        const root = document.getElementById(rootId);
        root.innerHTML = "";
        const maxValue = Math.max(1, ...entries.map(item => Number(item.value || 0)));
        entries.forEach(item => {
            const row = document.createElement("div");
            row.className = "bar";
            const pct = Math.max(0, Math.min(100, (Number(item.value || 0) / maxValue) * 100));
            row.innerHTML = `
                <div class="bar-name">${item.label}</div>
                <div class="bar-track"><div class="bar-fill ${colorResolver(item.key)}" style="width:${pct}%"></div></div>
                <div class="bar-value">${fmtNumber(item.value)}</div>
            `;
            root.appendChild(row);
        });
    }

    function renderLeaderboard(rows) {
        const body = document.getElementById("leaderboard-body");
        body.innerHTML = "";
        if (!rows.length) {
            body.innerHTML = '<tr><td colspan="5" class="muted">暂无拥堵源数据</td></tr>';
            return;
        }

        rows.slice(0, 12).forEach((row, idx) => {
            const tr = document.createElement("tr");
            let tagClass = "";
            if (isTruckType(row.object_type)) tagClass = "truck";
            else if (isNonMotorType(row.object_type)) tagClass = "non-motor";
            tr.innerHTML = `
                <td>${idx + 1}</td>
                <td>${row.entity}</td>
                <td><span class="tag ${tagClass}">${row.object_type || "UNKNOWN"}</span></td>
                <td>${Number(row.total_weight || 0).toFixed(2)}</td>
                <td>${fmtNumber(row.frame_count)}</td>
            `;
            body.appendChild(tr);
        });
    }

    function renderTimeline(series) {
        const svg = document.getElementById("timeline-svg");
        const note = document.getElementById("timeline-note");
        svg.innerHTML = "";

        if (!series.length) {
            note.textContent = "暂无时间线数据";
            return;
        }

        note.textContent = `样本帧: ${series.length}`;
        const width = 1000;
        const height = 190;
        const padX = 22;
        const padY = 18;

        const maxScore = Math.max(1, ...series.map(item => Number(item.score || 0)));
        const points = series.map((item, idx) => {
            const x = padX + (idx / Math.max(1, series.length - 1)) * (width - padX * 2);
            const y = height - padY - ((Number(item.score || 0) / maxScore) * (height - padY * 2));
            return { x, y, item };
        });

        const grid = document.createElementNS("http://www.w3.org/2000/svg", "g");
        for (let i = 0; i <= 4; i++) {
            const y = padY + (i / 4) * (height - padY * 2);
            const line = document.createElementNS("http://www.w3.org/2000/svg", "line");
            line.setAttribute("x1", String(padX));
            line.setAttribute("y1", String(y));
            line.setAttribute("x2", String(width - padX));
            line.setAttribute("y2", String(y));
            line.setAttribute("stroke", "#d7ccbb");
            line.setAttribute("stroke-width", "1");
            grid.appendChild(line);
        }
        svg.appendChild(grid);

        const areaPath = document.createElementNS("http://www.w3.org/2000/svg", "path");
        const linePath = document.createElementNS("http://www.w3.org/2000/svg", "path");

        const pathD = points.map((p, i) => `${i === 0 ? "M" : "L"}${p.x},${p.y}`).join(" ");
        const areaD = `${pathD} L${points[points.length - 1].x},${height - padY} L${points[0].x},${height - padY} Z`;

        areaPath.setAttribute("d", areaD);
        areaPath.setAttribute("fill", "rgba(249, 115, 22, 0.18)");
        areaPath.setAttribute("stroke", "none");

        linePath.setAttribute("d", pathD);
        linePath.setAttribute("fill", "none");
        linePath.setAttribute("stroke", "#ea580c");
        linePath.setAttribute("stroke-width", "2.5");

        svg.appendChild(areaPath);
        svg.appendChild(linePath);

        points.forEach((p, idx) => {
            if (idx % Math.max(1, Math.floor(points.length / 24)) !== 0) return;
            const dot = document.createElementNS("http://www.w3.org/2000/svg", "circle");
            dot.setAttribute("cx", String(p.x));
            dot.setAttribute("cy", String(p.y));
            dot.setAttribute("r", "2.4");
            dot.setAttribute("fill", "#0f766e");
            svg.appendChild(dot);
        });
    }

    function renderFrames(frames) {
        const root = document.getElementById("frames-grid");
        root.innerHTML = "";
        if (!frames.length) {
            root.innerHTML = '<div class="muted">暂无帧数据</div>';
            return;
        }

        frames.slice(0, 18).forEach(frame => {
            const card = document.createElement("article");
            card.className = "frame-card";
            const causes = (frame.dominant_causes || []).slice(0, 2).join(" / ") || "-";
            const source = (frame.source_entities || []).slice(0, 2).join(", ") || "-";
            const rawSrc = frame.raw_image ? `/api/image?path=${encodeURIComponent(frame.raw_image)}` : "";
            const bevSrc = frame.bev_image ? `/api/image?path=${encodeURIComponent(frame.bev_image)}` : "";

            card.innerHTML = `
                <div class="frame-head">
                    <div class="frame-id">Frame ${frame.frame_id}</div>
                    <div class="score">Score ${frame.slowdown_score}</div>
                </div>
                <div class="frame-body">
                    <div class="kv"><span>Class</span><strong>${frame.slowdown_class_label || frame.slowdown_class}</strong></div>
                    <div class="kv"><span>Sources</span><strong>${source}</strong></div>
                    <div class="kv"><span>Causes</span><strong>${causes}</strong></div>
                    <div class="thumb-row">
                        <div class="thumb">
                            ${rawSrc ? `<img loading="lazy" src="${rawSrc}" alt="raw">` : ""}
                            ${rawSrc ? `<a target="_blank" href="${rawSrc}">Raw</a>` : ""}
                        </div>
                        <div class="thumb">
                            ${bevSrc ? `<img loading="lazy" src="${bevSrc}" alt="bev">` : ""}
                            ${bevSrc ? `<a target="_blank" href="${bevSrc}">BEV</a>` : ""}
                        </div>
                    </div>
                </div>
            `;
            root.appendChild(card);
        });
    }

    function render(data) {
        const meta = data.meta || {};
        const dist = data.distributions || {};
        const levels = dist.slowdown_levels || {};
        const classes = dist.slowdown_classes || {};
        const causes = dist.dominant_causes || {};
        const sourceRows = ((data.leaderboard || {}).source_weighted || []);
        const topSource = sourceRows.length ? sourceRows[0].entity : "-";

        document.getElementById("run-info").textContent = `${meta.selected_run_name || "未选择运行"} · 最近更新时间 ${meta.last_run_time || "-"}`;
        document.getElementById("meta-total").textContent = fmtNumber(meta.total);
        document.getElementById("meta-assessed").textContent = fmtNumber(meta.assessed);
        document.getElementById("meta-pending").textContent = fmtNumber(meta.pending);
        document.getElementById("meta-top-source").textContent = topSource;
        document.getElementById("dist-note").textContent = `生成时间 ${meta.generated_at || "-"}`;

        renderBars("level-bars", [
            { key: "high", label: "High", value: levels.high || 0 },
            { key: "medium", label: "Medium", value: levels.medium || 0 },
            { key: "low", label: "Low", value: levels.low || 0 },
        ], key => key);

        const classEntries = Object.keys(classes)
            .map(key => ({ key, label: classLabel(key), value: classes[key] }))
            .sort((a, b) => Number(b.value || 0) - Number(a.value || 0));
        renderBars("class-bars", classEntries, () => "neutral");

        const causeEntries = Object.keys(causes)
            .map(key => ({ key, label: key, value: causes[key] }))
            .slice(0, 8);
        renderBars("cause-bars", causeEntries, () => "neutral");

        renderLeaderboard(sourceRows);
        renderTimeline(data.score_series || []);
        renderFrames(data.top_frames || []);
    }

    async function loadData() {
        const response = await fetch("/api/showcase/data", { cache: "no-store" });
        if (!response.ok) throw new Error(`HTTP ${response.status}`);
        const data = await response.json();
        render(data);
    }

    async function boot() {
        bindShowcaseAppearance();
        const btn = document.getElementById("refresh-btn");
        btn.addEventListener("click", () => loadData().catch(err => alert(`刷新失败: ${err.message}`)));
        await loadData();
        setInterval(() => {
            loadData().catch(() => {});
        }, 30000);
    }

    boot().catch(err => {
        alert(`展示页加载失败: ${err.message}`);
    });

