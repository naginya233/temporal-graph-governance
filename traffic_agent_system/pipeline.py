import os
import json
import argparse
from datetime import datetime
from typing import Any, Dict, List, Optional

from agents.cognitive_agents import SceneAgent, EventAgent
from core.frame_asset_index import FrameAssetIndexer
from core.io_utils import SceneGraphLoader, SpatialContextLoader
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
        label_virtuallidar_dir: Optional[str] = None,
        label_camera_dir: Optional[str] = None,
        calib_virtuallidar_to_world_dir: Optional[str] = None,
        map_elements_dir: Optional[str] = None,
        following_filter_enabled: bool = True,
        following_min_longitudinal_gap: float = 1.5,
        following_max_longitudinal_gap: float = 35.0,
        following_max_lateral_offset: float = 3.2,
        following_min_heading_cos: float = 0.35,
        following_require_same_lane: bool = True,
    ):
        self.data_dir = data_dir
        self.loader = SceneGraphLoader(data_dir)
        self.spatial_loader = SpatialContextLoader(
            label_virtuallidar_dir=label_virtuallidar_dir,
            label_camera_dir=label_camera_dir,
            calib_virtuallidar_to_world_dir=calib_virtuallidar_to_world_dir,
            map_elements_dir=map_elements_dir,
        )
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
        self.following_filter = {
            "enabled": following_filter_enabled,
            "min_longitudinal_gap": following_min_longitudinal_gap,
            "max_longitudinal_gap": following_max_longitudinal_gap,
            "max_lateral_offset": following_max_lateral_offset,
            "min_heading_cos": following_min_heading_cos,
            "require_same_lane": following_require_same_lane,
        }

    def _prepare_output_file(self) -> str:
        os.makedirs(self.output_dir, exist_ok=True)
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        return os.path.join(self.output_dir, f"run_{ts}.jsonl")

    def run_pipeline(self, max_frames: int = 5) -> str:
        print("=== 交通场景图治理管道 ===")
        print(f"数据目录: {self.data_dir}")
        print(
            "following 空间过滤: enabled={enabled}, min_long={min_long}, max_long={max_long}, max_lat={max_lat}, min_cos={min_cos}, same_lane={same_lane}".format(
                enabled=self.following_filter["enabled"],
                min_long=self.following_filter["min_longitudinal_gap"],
                max_long=self.following_filter["max_longitudinal_gap"],
                max_lat=self.following_filter["max_lateral_offset"],
                min_cos=self.following_filter["min_heading_cos"],
                same_lane=self.following_filter["require_same_lane"],
            )
        )

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
        slowdown_level_counts = {
            "low": 0,
            "medium": 0,
            "high": 0,
        }
        slowdown_class_counts = {
            "normal_controlled_queue": 0,
            "sustained_slowdown": 0,
            "anomalous_slowdown": 0,
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

            spatial_context = self.spatial_loader.load(frame_id=frame_id, scene_graph_dict=optimized_sg_data)
            scene_insights = self.scene_agent.process(
                frame_id,
                optimized_sg_data,
                spatial_context=spatial_context,
                following_filter=self.following_filter,
            )
            event_analysis = self.event_agent.analyze(scene_insights)
            governance_report = event_analysis["report"]

            if self.enable_temporal_calibration:
                calibration_result = self.calibrator.calibrate(
                    frame_id=frame_id,
                    scene_graph_dict=optimized_sg_data,
                    event_analysis=event_analysis,
                )
                event_analysis["raw_slowdown"] = calibration_result["raw_slowdown"]
                event_analysis["slowdown"] = calibration_result["calibrated_slowdown"]
                event_analysis["raw_risk"] = calibration_result["raw_risk"]
                event_analysis["risk"] = calibration_result["calibrated_risk"]
                event_analysis["temporal_features"] = calibration_result["temporal_features"]
                governance_report += (
                    "\n[时序一致性校准] "
                    f"raw={calibration_result['raw_slowdown'].get('level', 'unknown')}({calibration_result['raw_slowdown'].get('score', 0)}) -> "
                    f"calibrated={calibration_result['calibrated_slowdown']['level']}({calibration_result['calibrated_slowdown']['score']}), "
                    f"persistent={calibration_result['temporal_features']['persistent_edge_count']}, "
                    f"transient={calibration_result['temporal_features']['transient_edge_count']}"
                )

            slowdown = event_analysis.get("slowdown") or event_analysis.get("risk") or {}
            slowdown_level = str(slowdown.get("level", "low")).lower()
            slowdown_level_counts[slowdown_level] = slowdown_level_counts.get(slowdown_level, 0) + 1

            slowdown_class = str(slowdown.get("class", "normal_controlled_queue"))
            slowdown_class_counts[slowdown_class] = slowdown_class_counts.get(slowdown_class, 0) + 1

            print(governance_report)

            assets = self.asset_indexer.get_frame_assets(frame_id)

            record = {
                "frame_id": frame_id,
                "file": os.path.basename(filepath),
                "assets": assets,
                "spatial_context": {
                    "available": bool(spatial_context.get("available", False)),
                    "source": str(spatial_context.get("source", "none")),
                    "calibrated_to_world": bool(spatial_context.get("calibrated_to_world", False)),
                    "map_elements_file": spatial_context.get("map_elements_file"),
                    "map_elements_available": bool(spatial_context.get("map_elements_available", False)),
                    "stats": spatial_context.get("stats", {}),
                },
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
            "slowdown_levels": slowdown_level_counts,
            "risk_levels": slowdown_level_counts,
            "slowdown_classes": slowdown_class_counts,
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
    parser.add_argument(
        "--label-virtuallidar-dir",
        default=r"d:\Research\Project2\dairv2xspd\dairv2xspd\label\virtuallidar",
        help="Directory for per-frame label/virtuallidar json files",
    )
    parser.add_argument(
        "--label-camera-dir",
        default=r"d:\Research\Project2\dairv2xspd\dairv2xspd\label\camera",
        help="Directory for per-frame label/camera json files (fallback)",
    )
    parser.add_argument(
        "--calib-virtuallidar-to-world-dir",
        default=r"d:\Research\Project2\dairv2xspd\dairv2xspd\calib\virtuallidar_to_world",
        help="Directory for per-frame calib/virtuallidar_to_world json files",
    )
    parser.add_argument(
        "--map-elements-dir",
        default=r"d:\Research\Project2\infrastructure\data\infrastructure-side\map_elements_results",
        help="Directory for per-frame map_elements json files",
    )
    parser.add_argument("--max-frames", type=int, default=10, help="Max number of frames to process")
    parser.add_argument("--no-llm", action="store_true", help="Disable Ollama inference")
    parser.add_argument("--no-report", action="store_true", help="Disable markdown/html report generation")
    parser.add_argument("--disable-temporal-calibration", action="store_true", help="Disable temporal consistency calibration")
    parser.add_argument("--disable-following-spatial-filter", action="store_true", help="Disable following spatial consistency filtering")
    parser.add_argument("--following-min-longitudinal-gap", type=float, default=1.5, help="Minimum forward gap to keep following edge")
    parser.add_argument("--following-max-longitudinal-gap", type=float, default=35.0, help="Maximum forward gap to keep following edge")
    parser.add_argument("--following-max-lateral-offset", type=float, default=3.2, help="Maximum lateral offset to keep following edge")
    parser.add_argument("--following-min-heading-cos", type=float, default=0.35, help="Minimum heading cosine between follower and leader")
    parser.add_argument("--following-require-same-lane", action="store_true", default=True, help="Require follower and leader on the same lane id")
    parser.add_argument("--following-allow-cross-lane", action="store_false", dest="following_require_same_lane", help="Allow follower and leader on different lanes")
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
        label_virtuallidar_dir=args.label_virtuallidar_dir,
        label_camera_dir=args.label_camera_dir,
        calib_virtuallidar_to_world_dir=args.calib_virtuallidar_to_world_dir,
        map_elements_dir=args.map_elements_dir,
        following_filter_enabled=not args.disable_following_spatial_filter,
        following_min_longitudinal_gap=args.following_min_longitudinal_gap,
        following_max_longitudinal_gap=args.following_max_longitudinal_gap,
        following_max_lateral_offset=args.following_max_lateral_offset,
        following_min_heading_cos=args.following_min_heading_cos,
        following_require_same_lane=args.following_require_same_lane,
    )
    pipeline.run_pipeline(max_frames=args.max_frames)
