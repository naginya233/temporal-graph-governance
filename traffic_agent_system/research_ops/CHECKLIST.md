# CVPR Non-Writing Checklist

## Phase 1: Protocol Lock

- [ ] Freeze task definitions (frame, temporal, structural)
- [ ] Freeze split policy and seed
- [ ] Freeze metric definitions
- [ ] Freeze runtime measurement method

## Phase 2: Baselines

- [ ] Run rule_only baseline
- [ ] Run graph_only baseline
- [ ] Run full_system baseline
- [ ] Integrate at least one external baseline

## Phase 3: Ablations

- [ ] Remove temporal segmenter
- [ ] Remove pruning logic
- [ ] Remove LLM reasoning
- [ ] Remove conflict-chain logic

## Phase 4: Robustness

- [ ] Cross-scene evaluation
- [ ] Calibration perturbation test
- [ ] Relation noise sensitivity test

## Phase 5: Efficiency

- [ ] p50/p95 latency
- [ ] Throughput FPS
- [ ] Peak memory
- [ ] Accuracy-efficiency tradeoff plot

## Phase 6: Reproducibility

- [ ] One-command suite run
- [ ] One-command summary generation
- [ ] Manifest and logs archived
- [ ] Full environment and dependency snapshot
