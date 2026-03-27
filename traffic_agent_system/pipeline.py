import os
import json
import argparse
from datetime import datetime
from typing import Any, Dict, List

from agents.cognitive_agents import SceneAgent, EventAgent
from core.frame_asset_index import FrameAssetIndexer
from core.io_utils import SceneGraphLoader
from governance.temporal_consistency_calibrator import TemporalConsistencyCalibrator
from governance.temporal_event_segmenter import TemporalEventSegmenter
from optimization.topology_pruning import DynamicTopologyPruner
from reporting.review_report import ReviewReportBuilder

class TrafficGovernancePipeline:
    """
    Main orchestrator for the Cognitive Chain Driven Multi-Agent Collaboration Framework
    """
    def __init__(
        self,
        data_dir: str,
        bev_dir: str,
        raw_image_dir: str,
        use_llm: bool = True,
        model_name: str = "qwen3-vl:4b",
        output_dir: str = "outputs",
        generate_report: bool = True,
        enable_temporal_calibration: bool = True,
        calibration_alpha: float = 0.7,
        calibration_persistence_window: int = 2,
    ):
        self.data_dir = data_dir
        self.loader = SceneGraphLoader(data_dir)
        self.asset_indexer = FrameAssetIndexer(data_dir, bev_dir, raw_image_dir)
        self.scene_agent = SceneAgent()
        self.event_agent = EventAgent(use_llm=use_llm, model_name=model_name)
        self.segmenter = TemporalEventSegmenter(min_active_level="medium")
        self.pruner = DynamicTopologyPruner()
        self.output_dir = output_dir
        self.generate_report = generate_report
        self.report_builder = ReviewReportBuilder(output_dir)
        self.enable_temporal_calibration = enable_temporal_calibration
        self.calibrator = TemporalConsistencyCalibrator(
            alpha=calibration_alpha,
            persistence_window=calibration_persistence_window,
        )

    def _prepare_output_file(self) -> str:
        os.makedirs(self.output_dir, exist_ok=True)
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        return os.path.join(self.output_dir, f"run_{ts}.jsonl")

    def run_pipeline(self, max_frames: int = 5) -> str:
        print("=== 交通场景图治理管道 ===")
        print(f"数据目录: {self.data_dir}")

        output_file = self._prepare_output_file()
        scene_files = self.loader.iter_files(max_frames=max_frames)
        asset_summary = self.asset_indexer.get_summary()
        print(f"待处理帧数: {len(scene_files)}")
        print(
            "资产对齐: sg={scene_graph_frames}, bev={bev_frames}, raw={raw_frames}, complete={complete_frames}".format(
                scene_graph_frames=asset_summary["scene_graph_frames"],
                bev_frames=asset_summary["bev_frames"],
                raw_frames=asset_summary["raw_frames"],
                complete_frames=asset_summary["complete_frames"],
            )
        )

        processed = 0
        skipped = 0
        records: List[Dict[str, Any]] = []
        risk_level_counts = {
            "low": 0,
            "medium": 0,
            "high": 0,
        }

        for filepath in scene_files:
            try:
                frame_id, sg_data = self.loader.load(filepath)
            except Exception as exc:
                skipped += 1
                print(f"[跳过] {os.path.basename(filepath)} 加载失败: {exc}")
                continue

            print(f"\n[处理帧 {frame_id}]")

            optimized_sg_data, prune_stats = self.pruner.apply_knowledge_mask(sg_data)
            print(
                "[剪枝] total={total_edges}, kept={kept_edges}, pruned={pruned_edges}, ratio={ratio:.1f}%".format(
                    total_edges=prune_stats["total_edges"],
                    kept_edges=prune_stats["kept_edges"],
                    pruned_edges=prune_stats["pruned_edges"],
                    ratio=prune_stats["compression_ratio"] * 100,
                )
            )

            scene_insights = self.scene_agent.process(frame_id, optimized_sg_data)
            event_analysis = self.event_agent.analyze(scene_insights)
            governance_report = event_analysis["report"]

            if self.enable_temporal_calibration:
                calibration_result = self.calibrator.calibrate(
                    frame_id=frame_id,
                    scene_graph_dict=optimized_sg_data,
                    event_analysis=event_analysis,
                )
                event_analysis["raw_risk"] = calibration_result["raw_risk"]
                event_analysis["risk"] = calibration_result["calibrated_risk"]
                event_analysis["temporal_features"] = calibration_result["temporal_features"]
                governance_report += (
                    "\n[时序一致性校准] "
                    f"raw={calibration_result['raw_risk'].get('level', 'unknown')}({calibration_result['raw_risk'].get('score', 0)}) -> "
                    f"calibrated={calibration_result['calibrated_risk']['level']}({calibration_result['calibrated_risk']['score']}), "
                    f"persistent={calibration_result['temporal_features']['persistent_edge_count']}, "
                    f"transient={calibration_result['temporal_features']['transient_edge_count']}"
                )

            risk_level = event_analysis["risk"]["level"]
            risk_level_counts[risk_level] = risk_level_counts.get(risk_level, 0) + 1

            print(governance_report)

            assets = self.asset_indexer.get_frame_assets(frame_id)

            record = {
                "frame_id": frame_id,
                "file": os.path.basename(filepath),
                "assets": assets,
                "prune_stats": prune_stats,
                "scene_insights": scene_insights,
                "event_analysis": event_analysis,
                "governance_report": governance_report,
            }
            with open(output_file, "a", encoding="utf-8") as out:
                out.write(json.dumps(record, ensure_ascii=False) + "\n")

            records.append(record)
            processed += 1

        global_stats = self.pruner.get_global_stats()
        event_segments = self.segmenter.segment(records)

        summary = {
            "processed": processed,
            "skipped": skipped,
            "risk_levels": risk_level_counts,
            "global_pruning": global_stats,
            "temporal_calibration": self.calibrator.summary() if self.enable_temporal_calibration else {"enabled": False},
            "asset_coverage": asset_summary,
            "event_segments": len(event_segments),
            "output_file": output_file,
        }

        summary_file = os.path.splitext(output_file)[0] + "_summary.json"
        with open(summary_file, "w", encoding="utf-8") as out:
            json.dump(
                {
                    "summary": summary,
                    "event_segments": event_segments,
                },
                out,
                ensure_ascii=False,
                indent=2,
            )
        summary["summary_file"] = summary_file

        if self.generate_report:
            report_files = self.report_builder.build(summary, records, event_segments)
            summary["report_files"] = report_files

        print("\n=== 运行汇总 ===")
        print(json.dumps(summary, ensure_ascii=False, indent=2))
        return output_file

            

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Traffic scene graph governance pipeline")
    parser.add_argument(
        "--data-dir",
        default=r"d:\Research\Project2\infrastructure\data\infrastructure-side\scene_graph_results",
        help="Directory that contains *_scene_graph.json files",
    )
    parser.add_argument(
        "--bev-dir",
        default=r"d:\Research\Project2\infrastructure\data\infrastructure-side\intersection_vis_results",
        help="Directory that contains *_intersection.png files",
    )
    parser.add_argument(
        "--raw-image-dir",
        default=r"d:\Research\Project2\dairv2xspd\dairv2xspd\frames",
        help="Directory that contains raw *.jpg files",
    )
    parser.add_argument("--max-frames", type=int, default=10, help="Max number of frames to process")
    parser.add_argument("--no-llm", action="store_true", help="Disable Ollama inference")
    parser.add_argument("--no-report", action="store_true", help="Disable markdown/html report generation")
    parser.add_argument("--disable-temporal-calibration", action="store_true", help="Disable temporal consistency calibration")
    parser.add_argument("--calibration-alpha", type=float, default=0.7, help="EMA alpha for temporal calibration")
    parser.add_argument("--calibration-persistence-window", type=int, default=2, help="Persistent edge threshold in frames")
    parser.add_argument("--model", default="qwen3-vl:4b", help="Ollama model name")
    parser.add_argument("--output-dir", default="outputs", help="Directory to store run jsonl")
    args = parser.parse_args()

    pipeline = TrafficGovernancePipeline(
        data_dir=args.data_dir,
        bev_dir=args.bev_dir,
        raw_image_dir=args.raw_image_dir,
        use_llm=not args.no_llm,
        model_name=args.model,
        output_dir=args.output_dir,
        generate_report=not args.no_report,
        enable_temporal_calibration=not args.disable_temporal_calibration,
        calibration_alpha=args.calibration_alpha,
        calibration_persistence_window=args.calibration_persistence_window,
    )
    pipeline.run_pipeline(max_frames=args.max_frames)
