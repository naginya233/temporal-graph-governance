# DairV2X 治理主控台

该工具已整合两部分能力：

- 主功能：`traffic_agent_system` 运行控制 + 治理结果可视化审阅
- 次功能：场景图关系校对

目标是实现“前端可控后端运行”：在一个页面内启动/停止治理管道、查看实时日志、切换运行结果并审阅风险帧。

## 功能概览

### 1) 主功能: 治理运行与审阅

- 前端直接启动后端 `pipeline.py` 异步运行
- 支持设置：
  - `max_frames`
  - `model`
  - `use_llm`
  - `generate_report`
  - `data_dir` / `bev_dir` / `raw_image_dir` / `output_dir`
- 实时状态面板：
  - 运行状态、PID、开始/结束时间、退出码、最后产物路径
  - 实时日志尾部展示
- 运行结束后可自动刷新治理索引并进入审阅流
- 治理审阅卡片包含：原图、BEV 图、风险等级、主因标签、治理报告、LLM 结论

### 2) 次功能: 关系校对

- 保留原有关系校对流程
- 支持 `correct / incorrect / skip / undo`
- 与主功能共享图像查看和路径配置

## 安装

```bash
pip install -r requirements.txt
```

`requirements.txt` 默认包含：

- `Flask==3.0.0`

## 启动

```bash
python app.py
```

打开浏览器：`http://127.0.0.1:5000`

## 配置项说明

在“设置路径”中可配置：

- `sg_dir`: Scene Graph JSON 目录
- `img_dir`: 原图目录
- `schematic_dir`: BEV 场景图目录
- `gov_outputs_dir`: 治理输出目录（`run_*.jsonl`）
- `traffic_system_dir`: `traffic_agent_system` 根目录
- `pipeline_script`: 一般为 `traffic_agent_system/pipeline.py`
- `pipeline_python`: 运行 pipeline 的 Python 可执行文件

## 目录与数据约定

- 原图命名：`{frame_id}.jpg`
- BEV 命名：`{frame_id}_intersection.png`
- 治理输出：
  - `run_*.jsonl`
  - `run_*_summary.json`
  - 其他报告文件（可选）

## 快捷键

- `1`: 切到治理主功能模式
- `2`: 切到关系校对次功能模式
- `Y`: 确认（治理）或正确（校对）
- `N`: 存疑（治理）或错误（校对）
- `S`: 跳过
- `B` / `←`: 回退上一张

## 备注

- 本工具只消费场景图及其下游产物，不改动视觉到场景图生成链路。
- 治理运行采用后端异步执行，页面可持续查看运行日志与状态。

## E2E 冒烟回归 (Playwright)

在 `DairV2X_SceneGraph_Validator` 目录执行：

```bash
npm install
npx playwright install chromium
```

运行主控台 + showcase 冒烟：

```bash
npm run test:e2e:smoke
```

可选：运行本地“启动/停止管线”流程回归（默认跳过，需显式开启）：

PowerShell:

```powershell
$env:RUN_PIPELINE_FLOW='1'
npm run test:e2e:pipeline
```

说明：若本地 Python 命令不是 `python`，可通过环境变量覆盖：

PowerShell:

```powershell
$env:PYTHON_CMD='d:/Research/Project2/.venv/bin/python.exe'
npm run test:e2e:smoke
```
