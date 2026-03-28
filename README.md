# 交通治理与审阅一体化包

本目录是可直接发布的快照包，整合了两套系统：

1. traffic_agent_system
	 基于场景图的交通治理分析流水线。

2. DairV2X_SceneGraph_Validator
	 治理优先的 Web 审阅台，包含关系校对次模式。

本版本重点增强：

- 治理模式下支持动态 BEV 重渲染高亮。
- 动态渲染与静态图并行管线，开关可控。
- 地图元素风格统一（路口、车道、斑马线、停止线、安全岛、相机位）。
- 目标框坐标由 lidar 转 world 后绘制，避免聚集到角落。

---

## 一、目录结构

- traffic_agent_system/
	治理流水线主工程。

- DairV2X_SceneGraph_Validator/
	Web 端与后端 API，负责审阅、运行控制和可视化。

- requirements.txt
	根依赖入口，覆盖两套系统运行所需包。

- Dockerfile
- docker-compose.yml
	容器化运行文件。

- UPLOAD_GUIDE.md
	GitHub 上传简版指引。

---

## 二、环境要求

- Python 3.10 及以上（建议 3.10/3.11）
- Windows 或 Linux
- 可访问数据集目录（原图、BEV、标注、标定、地图元素）

建议使用独立虚拟环境。

Windows（PowerShell）示例：

```bash
python -m venv .venv
.venv\Scripts\activate
python -m pip install -U pip
python -m pip install -r requirements.txt
```

如果虚拟环境内 pip 缺失，可先执行：

```bash
python -m ensurepip --upgrade
python -m pip install -U pip
```

---

## 三、快速启动

### 1) 启动 Web 审阅台

```bash
cd DairV2X_SceneGraph_Validator
python app.py
```

默认地址：

- http://127.0.0.1:5000

### 2) 启动治理流水线（命令行方式）

```bash
cd traffic_agent_system
python pipeline.py --max-frames 20 --no-llm
```

也可以在 Web 页面内直接启动/停止流水线，并查看日志与状态。

---

## 四、Web 功能说明

### 1) 模式

- 治理审阅模式（主模式）
	查看原图、BEV、治理报告、主因标签，进行确认/存疑/跳过。

- 关系校对模式（次模式）
	对关系样本进行 correct/incorrect/skip。

### 2) 动态 BEV 高亮

治理模式中提供开关：动态高亮 BEV。

- 关闭时：使用静态 BEV 原图，不显示前端叠加高亮框。
- 开启时：调用后端动态渲染接口，根据当前选中对象重绘 BEV。

接口：

- GET /api/governance/render_bev?frame_id=...&entities=a,b,c

### 3) 车流对象联动

在治理卡片中点击对象/个体/源头后，会更新当前聚焦实体集合。

- 动态 BEV 开启：后端重渲染并返回高亮结果。
- 动态 BEV 关闭：仅保留静态图展示。

---

## 五、数据与路径约定

请在 Web 设置中配置以下路径（支持绝对路径）：

- sg_dir
	Scene Graph JSON 目录。

- img_dir
	原图目录。

- schematic_dir
	静态 BEV 图目录。

- gov_outputs_dir
	治理输出目录（run_*.jsonl 及 summary）。

- traffic_system_dir
	traffic_agent_system 根目录。

- pipeline_script
	一般为 traffic_agent_system/pipeline.py。

- pipeline_python
	运行 pipeline 的 Python 可执行文件。

动态渲染相关目录（默认从配置中推断，也可手动设置）：

- label/virtuallidar
- calib/virtuallidar_to_world
- map_elements_results

命名约定：

- 帧 ID：例如 001438
- 标注文件：001438.json
- 静态 BEV：001438_intersection.png

---

## 六、动态渲染设计说明

### 1) 并行管线

- 静态管线
	直接显示已有 BEV 图片。

- 动态管线
	后端读取地图元素、标注与标定，实时绘制并返回图像。

### 2) 坐标处理

对象框先在 lidar 坐标系下构建，再通过 virtuallidar_to_world 变换到 world 坐标。

这样可与 map elements 在同一坐标系叠加，避免错位和聚集问题。

### 3) 渲染内容

动态管线绘制：

- junction（含选中路口高亮）
- lane（交叉口内）
- crosswalk
- stopline
- island
- camera center
- object box + id

PNG 路径使用 matplotlib；无 matplotlib 时自动回退为 SVG 路径。

---

## 七、Docker 运行

构建镜像：

```bash
docker build -t traffic-governance-web:latest .
```

直接运行：

```bash
docker run --rm -p 5000:5000 traffic-governance-web:latest
```

使用 compose：

```bash
docker compose up -d --build
```

访问：

- http://127.0.0.1:5000
- http://127.0.0.1:5000/showcase

若数据目录在仓库外，请在 docker-compose.yml 中补充 host mount，并在页面设置中改路径。

---

## 八、Linux 边缘端一键部署（非 Docker）

仓库内提供部署脚本：

```bash
bash scripts/deploy_df2e518_linux.sh --with-service --install-dir /opt/temporal-graph-governance
```

常用参数：

```bash
bash scripts/deploy_df2e518_linux.sh --install-dir /opt/temporal-graph-governance
bash scripts/deploy_df2e518_linux.sh --with-service --skip-tests
bash scripts/deploy_df2e518_linux.sh --with-service --force-recreate
```

---

## 九、常见问题排查

### 1) 启动 app.py 报错：No module named flask

原因：当前 Python 环境未安装依赖。

处理：

```bash
python -m pip install -r requirements.txt
```

### 2) 动态 BEV 开关打开后无变化

检查项：

- 后端是否启动成功。
- frame_id 是否存在对应标注与标定文件。
- map_elements 目录是否可读。
- 浏览器是否拿到 /api/governance/render_bev 返回内容。

### 3) 对象位置明显错位

检查项：

- calib/virtuallidar_to_world 是否匹配当前帧。
- 标注是否来自 virtuallidar 坐标系。
- map_elements 与标注是否是同一批数据。

### 4) matplotlib 安装困难

系统会自动尝试 SVG 回退渲染；如需 PNG 路径，请补装 matplotlib。

---

## 十、快照打包与 GitHub 更新建议流程

### 1) 生成快照压缩包

```bash
Compress-Archive -Path ./github_upload_package/* -DestinationPath ./github_upload_package_YYYYMMDD_HHMMSS.zip -Force
```

### 2) 提交并推送

```bash
git add .
git commit -m "snapshot: update dynamic bev pipeline"
git push origin <your-branch>
```

建议每次快照同步记录：

- 分支名
- 提交哈希
- 关键改动点
- 对应 zip 文件名

---

## 十一、说明

- 本打包目录默认不包含大体量运行输出与机器私有配置。
- 首次启动后请先在 Web 设置页面完成路径校准。
- 若用于多人协作，建议固定 Python 版本和依赖版本，并保留一次可复现快照。
