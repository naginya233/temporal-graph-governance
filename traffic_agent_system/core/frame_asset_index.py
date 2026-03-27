import glob
import os
from typing import Dict, Optional


class FrameAssetIndexer:
    """Index scene graph json, BEV visualization, and raw image by frame id."""

    def __init__(self, scene_graph_dir: str, bev_dir: str, raw_image_dir: str):
        self.scene_graph_dir = scene_graph_dir
        self.bev_dir = bev_dir
        self.raw_image_dir = raw_image_dir

        self._scene_graph_map: Dict[str, str] = {}
        self._bev_map: Dict[str, str] = {}
        self._raw_map: Dict[str, str] = {}
        self.refresh()

    def refresh(self) -> None:
        self._scene_graph_map = self._build_map(
            os.path.join(self.scene_graph_dir, "*_scene_graph.json"),
            self._parse_scene_graph_frame_id,
        )
        self._bev_map = self._build_map(
            os.path.join(self.bev_dir, "*_intersection.png"),
            self._parse_bev_frame_id,
        )
        self._raw_map = self._build_map(
            os.path.join(self.raw_image_dir, "*.jpg"),
            self._parse_raw_frame_id,
        )

    @staticmethod
    def _build_map(pattern: str, parser) -> Dict[str, str]:
        mapped: Dict[str, str] = {}
        for file_path in sorted(glob.glob(pattern)):
            frame_id = parser(os.path.basename(file_path))
            if frame_id is not None:
                mapped[frame_id] = file_path
        return mapped

    @staticmethod
    def _parse_scene_graph_frame_id(filename: str) -> Optional[str]:
        if not filename.endswith("_scene_graph.json"):
            return None
        return filename.split("_", 1)[0]

    @staticmethod
    def _parse_bev_frame_id(filename: str) -> Optional[str]:
        if not filename.endswith("_intersection.png"):
            return None
        return filename.split("_", 1)[0]

    @staticmethod
    def _parse_raw_frame_id(filename: str) -> Optional[str]:
        name, ext = os.path.splitext(filename)
        if ext.lower() != ".jpg":
            return None
        return name

    def get_frame_assets(self, frame_id: str) -> Dict[str, object]:
        scene_graph_json = self._scene_graph_map.get(frame_id)
        bev_image = self._bev_map.get(frame_id)
        raw_image = self._raw_map.get(frame_id)

        availability = {
            "scene_graph_json": scene_graph_json is not None,
            "bev_image": bev_image is not None,
            "raw_image": raw_image is not None,
        }
        return {
            "scene_graph_json": scene_graph_json,
            "bev_image": bev_image,
            "raw_image": raw_image,
            "availability": availability,
            "is_complete": all(availability.values()),
        }

    def get_summary(self) -> Dict[str, int]:
        all_ids = set(self._scene_graph_map.keys())
        all_ids.update(self._bev_map.keys())
        all_ids.update(self._raw_map.keys())

        complete_frames = 0
        for frame_id in all_ids:
            if (
                frame_id in self._scene_graph_map
                and frame_id in self._bev_map
                and frame_id in self._raw_map
            ):
                complete_frames += 1

        return {
            "scene_graph_frames": len(self._scene_graph_map),
            "bev_frames": len(self._bev_map),
            "raw_frames": len(self._raw_map),
            "all_known_frames": len(all_ids),
            "complete_frames": complete_frames,
        }
