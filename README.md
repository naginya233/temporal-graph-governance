# Temporal Graph Governance

中文 | English

## 项目简介 (CN)

Temporal Graph Governance 是一个面向车路协同场景的交通治理与可解释审阅项目。项目将场景图推理、缓行风险分析、可视化审阅与运行编排整合到同一工作流中，支持研究验证、策略迭代和工程落地。

本仓库是用于发布和交付的集成包，包含核心分析系统与审阅控制台。

## Project Overview (EN)

Temporal Graph Governance is an integrated toolkit for traffic governance in V2X scenarios. It combines scene-graph reasoning, slowdown risk analysis, visual review, and run orchestration in one workflow for research, iteration, and deployment.

This snapshot is the distributable bundle that contains both the analysis engine and the review console.

---

## 系统组成 (CN)

1. traffic_agent_system
   场景图交通治理流水线，负责事件分析、风险评估与报告产出。

2. DairV2X_SceneGraph_Validator
   治理审阅优先的 Web 控制台，支持运行管线、查看日志、审核结果与关系校对。

## Components (EN)

1. traffic_agent_system
   Core pipeline for scene-graph traffic governance, risk scoring, and report generation.

2. DairV2X_SceneGraph_Validator
   Governance-first web console for pipeline control, live logs, result review, and relation validation.

---

## 核心能力 (CN)

- 治理流程闭环：从 pipeline 运行到审阅反馈在同一页面完成。
- 双模式审阅：治理审阅模式 + 关系校对模式。
- 动态 BEV 可视化：按需重渲染高亮对象，支持静态/动态切换。
- 地图元素叠加：路口、车道、斑马线、停止线、安全岛、相机位与目标框统一展示。
- 坐标一致性：对象从 lidar 坐标转换到 world 坐标，提升叠加准确性。

## Core Capabilities (EN)

- End-to-end governance loop from pipeline execution to human review.
- Dual review modes: governance review and relation validation.
- Dynamic BEV rendering with on-demand highlighting and static/dynamic switch.
- Unified map overlays: junctions, lanes, crosswalks, stop lines, islands, camera center, and object boxes.
- Coordinate consistency via lidar-to-world transformation for robust alignment.

---

## 目录结构 (CN)

- traffic_agent_system/: 治理流水线主工程。
- DairV2X_SceneGraph_Validator/: Web 服务与可视化审阅前后端。
- requirements.txt: 根依赖入口。
- Dockerfile, docker-compose.yml: 容器化部署文件。
- UPLOAD_GUIDE.md: 上传与发布说明。

## Repository Layout (EN)

- traffic_agent_system/: governance pipeline implementation.
- DairV2X_SceneGraph_Validator/: web app and visualization backend/frontend.
- requirements.txt: top-level dependency list.
- Dockerfile, docker-compose.yml: container deployment files.
- UPLOAD_GUIDE.md: upload and release notes.

---

## 快速开始 (CN)

### 1) 安装依赖

```bash
python -m venv .venv
.venv\Scripts\activate
python -m pip install -U pip
python -m pip install -r requirements.txt
```

### 2) 启动 Web 控制台

```bash
cd DairV2X_SceneGraph_Validator
python app.py
```

访问地址：http://127.0.0.1:5000

### 3) 启动治理流水线

```bash
cd traffic_agent_system
python pipeline.py --max-frames 20 --no-llm
```

## Quick Start (EN)

### 1) Install dependencies

```bash
python -m venv .venv
.venv\Scripts\activate
python -m pip install -U pip
python -m pip install -r requirements.txt
```

### 2) Start the web console

```bash
cd DairV2X_SceneGraph_Validator
python app.py
```

Open: http://127.0.0.1:5000

### 3) Run the governance pipeline

```bash
cd traffic_agent_system
python pipeline.py --max-frames 20 --no-llm
```

---

## 配置说明 (CN)

在 Web 设置页中配置以下路径：

- sg_dir: 场景图 JSON 目录
- img_dir: 原始图像目录
- schematic_dir: 静态 BEV 目录
- gov_outputs_dir: 治理输出目录
- traffic_system_dir: 流水线工程目录
- pipeline_script: pipeline.py 路径
- pipeline_python: 运行 pipeline 的 Python 解释器

动态 BEV 相关输入目录：

- label/virtuallidar
- calib/virtuallidar_to_world
- map_elements_results

## Configuration (EN)

Configure these paths in the web settings page:

- sg_dir: scene graph JSON directory
- img_dir: raw image directory
- schematic_dir: static BEV directory
- gov_outputs_dir: governance output directory
- traffic_system_dir: pipeline project directory
- pipeline_script: path to pipeline.py
- pipeline_python: Python interpreter used by pipeline

Dynamic BEV requires:

- label/virtuallidar
- calib/virtuallidar_to_world
- map_elements_results

---

## 动态 BEV 机制 (CN)

- 关闭动态开关：展示静态 BEV 图，不显示前端叠加框。
- 开启动态开关：请求后端重渲染接口并返回高亮图。
- 接口：GET /api/governance/render_bev?frame_id=...&entities=a,b,c
- 无 matplotlib 时自动回退 SVG 渲染。

## Dynamic BEV Behavior (EN)

- Dynamic off: show static BEV image without frontend overlay boxes.
- Dynamic on: call backend rendering API and return highlighted BEV output.
- API: GET /api/governance/render_bev?frame_id=...&entities=a,b,c
- SVG fallback is used when matplotlib is unavailable.

---

## 演示材料 / Demo Material

- 缓行评分演示文档（10 个典型场景对照表）:
   [docs/slowdown_scoring_demo.md](docs/slowdown_scoring_demo.md)
- 行人过街饱和统计定义文档:
   [docs/pedestrian_crossing_definition.md](docs/pedestrian_crossing_definition.md)

---

## 常见问题 (CN)

1. 启动失败提示 No module named flask
   请确认当前环境已安装 requirements.txt。

2. 开启动态 BEV 后没有变化
   请检查后端服务状态、frame 对应标注/标定是否存在、map_elements 路径是否正确。

3. 目标与地图错位
   请检查标定文件与帧号是否匹配，确认使用了 virtuallidar_to_world。

## FAQ (EN)

1. No module named flask
   Install dependencies from requirements.txt in the active environment.

2. Dynamic BEV shows no change
   Verify backend status, per-frame labels/calibration availability, and map_elements path.

3. Object-map misalignment
   Validate frame-calibration matching and ensure lidar-to-world transform is applied.

---

## 部署方式 (CN/EN)

- Local run: Python 直接运行 app.py 与 pipeline.py。
- Docker: 使用 Dockerfile 或 docker-compose.yml 启动。
- Edge Linux: 可使用 scripts/deploy_df2e518_linux.sh 一键部署。

---

## License / 许可

This project is open-sourced under the **MIT License**.

See the `LICENSE` file for details.

