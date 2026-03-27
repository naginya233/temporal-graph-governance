# Research Ops For CVPR

This folder is an execution layer for non-writing CVPR preparation.

It provides:
- protocol definition
- baseline and ablation matrices
- repeatable suite runner
- suite summarizer for quick comparison tables

## Files

- protocols/cvpr_protocol.yaml
- protocols/baseline_matrix.csv
- protocols/ablation_matrix.csv
- configs/suite_example.json
- scripts/run_suite.py
- scripts/summarize_suite.py

## Quick Start

1) Edit suite config:

- configs/suite_example.json

2) Run suite:

python research_ops/scripts/run_suite.py --suite research_ops/configs/suite_example.json

3) Summarize suite:

python research_ops/scripts/summarize_suite.py --result-root research_ops/results

4) Fill baseline/ablation matrices with measured numbers.

## Notes

- This layer does not modify visual-to-scene-graph generation.
- For strict reproducibility, keep random split seed and run environments fixed.
