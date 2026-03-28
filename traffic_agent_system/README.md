# Traffic Agent System

This folder contains a step-by-step implementation for using scene graph data in a following-based slow-queue analysis pipeline.

The pipeline does not modify the visual-to-scene-graph generation process. It consumes existing outputs:

- scene graph json files
- BEV visualization images
- raw camera images

## Structure

- `core/constants.py`: relation/type constants.
- `core/io_utils.py`: scene graph loading and validation, plus text-only spatial context loading (`label/calib`).
- `core/frame_asset_index.py`: frame-level alignment for scene graph/BEV/raw assets.
- `optimization/topology_pruning.py`: conservative pruning with per-frame/global stats.
- `governance/graph_analyzer.py`: following-relation graph analysis for convoy and queue indicators.
- `governance/temporal_consistency_calibrator.py`: frame-level slowdown temporal smoothing and consistency calibration.
- `governance/temporal_event_segmenter.py`: frame-level slowdown to temporal event segments.
- `agents/cognitive_agents.py`: following-centric scene analysis + slowdown reasoning (rule + optional Ollama).
- `reporting/review_report.py`: markdown/html review report generator.
- `pipeline.py`: CLI entry point and run orchestration.
- `research_ops/`: CVPR non-writing execution layer (protocol/matrices/scripts).
- `tests/test_graph_analyzer.py`: unit tests for key graph-analysis behaviors.
- `tests/test_frame_asset_index.py`: unit tests for frame-level multi-source alignment.
- `tests/test_temporal_consistency_calibrator.py`: unit tests for temporal consistency calibration behavior.
- `tests/test_temporal_event_segmenter.py`: unit tests for temporal event segmentation.

## Slowdown Definition

The current objective is full slowdown recognition with three categories:

- `normal_controlled_queue`: controlled queueing near stop lines / signal phases; no strong anomaly signature.
- `sustained_slowdown`: persistent queue or convoy behavior with notable discharge inefficiency.
- `anomalous_slowdown`: structurally abnormal slowdown (e.g., following cycles, severe merge bottlenecks, extra-long convoy under bottleneck).

The category is derived from following-structure indicators (`max_following_chain`, `convoy_count`, `merge_nodes`, `queue_density`, `cycle_detected`) and is output at frame level.

## Following Spatial Consistency Filter (Text-Only)

To reduce noisy following edges without using raw images, the pipeline can consume:

- `label/virtuallidar/*.json` (preferred) or `label/camera/*.json` (fallback)
- `calib/virtuallidar_to_world/*.json` (optional but recommended)

The filter removes following edges that violate configured geometric constraints:

- longitudinal gap out of range (`min_longitudinal_gap`, `max_longitudinal_gap`)
- lateral offset too large (`max_lateral_offset`)
- heading mismatch (`min_heading_cos`)
- optional lane mismatch (`require_same_lane`)

Per-frame diagnostics are exposed at `event_analysis.slowdown.metrics` and `scene_insights.following_health.following_filter`.

## Output Contract

Frame-level `event_analysis` uses slowdown-first schema with backward compatibility:

- primary: `event_analysis.slowdown`, `event_analysis.raw_slowdown`
- compatibility: `event_analysis.risk`, `event_analysis.raw_risk`

`slowdown` and `risk` keep aligned `score`/`level` values so existing downstream consumers continue to work during migration.

### Slowdown Object Schema (Per Frame)

`event_analysis.slowdown` now includes explicit entity/source fields for slowdown traffic-flow tracing:

- `individual_entities`: all entities involved in detected slowdown flows for the frame.
- `source_entities`: deduplicated slowdown sources (merge bottleneck nodes, cycle-lock nodes, queue-head nodes).
- `source_summary`: grouped source sets with counts.
- `slowdown_objects`: structured flow objects (`flow_id`, `flow_kind`, `individual_entities`, `queue_tail`, `queue_head`, `source_entities`, `source_type`, `upstream_to_source`).

Example (simplified):

```json
{
	"event_analysis": {
		"slowdown": {
			"level": "medium",
			"class": "sustained_slowdown",
			"individual_entities": ["car_11", "car_09", "car_03"],
			"source_entities": ["car_03"],
			"source_summary": {
				"merge_bottleneck_sources": [],
				"cycle_lock_sources": [],
				"queue_head_sources": ["car_03"],
				"source_count": 1
			},
			"slowdown_objects": [
				{
					"flow_id": "flow_1",
					"flow_kind": "convoy_chain",
					"individual_entities": ["car_11", "car_09", "car_03"],
					"queue_tail": "car_11",
					"queue_head": "car_03",
					"source_entities": ["car_03"],
					"source_type": "queue_head",
					"upstream_to_source": {
						"car_03": ["car_09"]
					}
				}
			]
		}
	}
}
```

## Run

Install dependencies first:

```bash
python -m pip install -r requirements.txt
```

```bash
python pipeline.py --max-frames 20 --no-llm
```

Disable temporal consistency calibration (for ablation):

```bash
python pipeline.py --max-frames 20 --no-llm --disable-temporal-calibration
```

Disable following spatial consistency filtering (ablation):

```bash
python pipeline.py --max-frames 20 --no-llm --disable-following-spatial-filter
```

Specify asset directories explicitly if needed:

```bash
python pipeline.py \
	--data-dir d:/Research/Project2/infrastructure/data/infrastructure-side/scene_graph_results \
	--bev-dir d:/Research/Project2/infrastructure/data/infrastructure-side/intersection_vis_results \
	--raw-image-dir d:/Research/Project2/dairv2xspd/dairv2xspd/frames \
	--label-virtuallidar-dir d:/Research/Project2/dairv2xspd/dairv2xspd/label/virtuallidar \
	--label-camera-dir d:/Research/Project2/dairv2xspd/dairv2xspd/label/camera \
	--calib-virtuallidar-to-world-dir d:/Research/Project2/dairv2xspd/dairv2xspd/calib/virtuallidar_to_world \
	--max-frames 20
```

Tune spatial filtering thresholds:

```bash
python pipeline.py \
	--max-frames 20 \
	--following-min-longitudinal-gap 1.0 \
	--following-max-longitudinal-gap 40.0 \
	--following-max-lateral-offset 5.0 \
	--following-min-heading-cos 0.0 \
	--following-require-same-lane
```

Enable local Ollama model:

```bash
python pipeline.py --max-frames 20 --model qwen3-vl:4b
```

## Output

Each run writes a JSONL file into `outputs/`:

- one line per frame
- includes pruning stats, scene insights, event analysis, final report

Additional files are generated per run:

- `run_*.jsonl`: frame-level records
- `run_*_summary.json`: global summary + temporal event segments
- `run_*_summary.md`: concise markdown summary
- `run_*_review.html`: visual review page with links/thumbnails

## Test

```bash
python -m unittest discover -s tests -p "test_*.py"
```

## Research Ops

Run suite:

```bash
python research_ops/scripts/run_suite.py --suite research_ops/configs/suite_example.json
```

Summarize suite:

```bash
python research_ops/scripts/summarize_suite.py --result-root research_ops/results
```
