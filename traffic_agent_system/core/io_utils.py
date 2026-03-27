import glob
import json
import os
from typing import Dict, Iterator, List, Optional, Tuple


class SceneGraphLoader:
    """Load and minimally validate scene graph json files."""

    REQUIRED_TOP_LEVEL_KEYS = (
        "image_id",
        "object_object_triples",
        "object_map_triples",
    )

    def __init__(self, data_dir: str):
        self.data_dir = data_dir

    def iter_files(self, max_frames: Optional[int] = None) -> List[str]:
        pattern = os.path.join(self.data_dir, "*.json")
        files = sorted(glob.glob(pattern))
        if max_frames is not None:
            files = files[:max_frames]
        return files

    def load(self, file_path: str) -> Tuple[str, Dict]:
        with open(file_path, "r", encoding="utf-8") as f:
            data = json.load(f)

        missing = [k for k in self.REQUIRED_TOP_LEVEL_KEYS if k not in data]
        if missing:
            raise ValueError(
                f"Invalid scene graph file: {os.path.basename(file_path)}; missing keys: {missing}"
            )

        frame_id = os.path.basename(file_path).split("_")[0]
        return frame_id, data
