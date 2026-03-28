# Traffic Agent System

This folder contains a step-by-step implementation for using scene graph data in a traffic governance pipeline.

The pipeline does not modify the visual-to-scene-graph generation process. It consumes existing outputs:

- scene graph json files
- BEV visualization images
- raw camera images

## Structure

- `core/constants.py`: relation/type constants.
- `core/io_utils.py`: scene graph loading and validation.
- `core/frame_asset_index.py`: frame-level alignment for scene graph/BEV/raw assets.
- `optimization/topology_pruning.py`: conservative pruning with per-frame/global stats.
- `governance/graph_analyzer.py`: relation-level graph analysis.
- `governance/temporal_consistency_calibrator.py`: frame risk temporal smoothing and consistency calibration.
- `governance/temporal_event_segmenter.py`: frame-level to temporal event segments.
- `agents/cognitive_agents.py`: scene analysis + event reasoning (rule + optional Ollama).
- `reporting/review_report.py`: markdown/html review report generator.
- `pipeline.py`: CLI entry point and run orchestration.
- `research_ops/`: CVPR non-writing execution layer (protocol/matrices/scripts).
- `tests/test_graph_analyzer.py`: unit tests for key graph-analysis behaviors.
- `tests/test_frame_asset_index.py`: unit tests for frame-level multi-source alignment.
- `tests/test_temporal_consistency_calibrator.py`: unit tests for temporal consistency calibration behavior.
- `tests/test_temporal_event_segmenter.py`: unit tests for temporal event segmentation.

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

Specify asset directories explicitly if needed:

```bash
python pipeline.py \
	--data-dir d:/Research/Project2/infrastructure/data/infrastructure-side/scene_graph_results \
	--bev-dir d:/Research/Project2/infrastructure/data/infrastructure-side/intersection_vis_results \
	--raw-image-dir d:/Research/Project2/dairv2xspd/dairv2xspd/frames \
	--max-frames 20
```

Enable local Ollama model:

```bash
python pipeline.py --max-frames 20 --model qwen3-vl:4b
```

Large-scale direct run without manual review:

```bash
python pipeline.py --max-frames 200 --no-review-mode --no-llm
```

Disable auto human-friendly rating report (structured output only):

```bash
python pipeline.py --max-frames 200 --no-review-mode --no-auto-human-report
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
- `run_*_risk_rating_structured.json`: structured risk-rating payload for downstream workflow
- `run_*_risk_rating_report.md`: human-friendly intersection risk rating report
- `run_*_risk_rating_report.html`: browser-ready human-friendly rating report

When `--no-review-mode` is enabled, the run is marked as direct delivery (`review_mode=none`) and can skip manual review while still producing structured and human-friendly reports.

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
