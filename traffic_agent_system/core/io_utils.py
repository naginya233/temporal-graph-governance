import glob
import json
import math
import os
from typing import Any, Dict, Iterator, List, Optional, Tuple


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


class SpatialContextLoader:
    """Load per-frame entity geometry from text annotations and calibration files."""

    def __init__(
        self,
        label_virtuallidar_dir: Optional[str] = None,
        label_camera_dir: Optional[str] = None,
        calib_virtuallidar_to_world_dir: Optional[str] = None,
        map_elements_dir: Optional[str] = None,
    ):
        self.label_virtuallidar_dir = self._normalize_dir(label_virtuallidar_dir)
        self.label_camera_dir = self._normalize_dir(label_camera_dir)
        self.calib_virtuallidar_to_world_dir = self._normalize_dir(calib_virtuallidar_to_world_dir)
        self.map_elements_dir = self._normalize_dir(map_elements_dir)

    @staticmethod
    def _normalize_dir(path: Optional[str]) -> Optional[str]:
        if path is None:
            return None
        cleaned = str(path).strip()
        if not cleaned:
            return None
        return os.path.abspath(cleaned)

    @staticmethod
    def _load_json_file(file_path: str) -> Any:
        with open(file_path, "r", encoding="utf-8") as f:
            return json.load(f)

    @staticmethod
    def _frame_file(base_dir: Optional[str], frame_id: str) -> Optional[str]:
        if not base_dir:
            return None
        file_path = os.path.join(base_dir, f"{frame_id}.json")
        if os.path.exists(file_path):
            return file_path
        return None

    @staticmethod
    def _safe_float(value: Any, default: float = 0.0) -> float:
        try:
            return float(value)
        except (TypeError, ValueError):
            return default

    @staticmethod
    def _parse_rotation_matrix(matrix_obj: Any) -> Optional[List[List[float]]]:
        if not isinstance(matrix_obj, list) or len(matrix_obj) != 3:
            return None
        rows: List[List[float]] = []
        for row in matrix_obj:
            if not isinstance(row, list) or len(row) != 3:
                return None
            rows.append([SpatialContextLoader._safe_float(item) for item in row])
        return rows

    @staticmethod
    def _parse_translation_vector(vector_obj: Any) -> Optional[List[float]]:
        if isinstance(vector_obj, list) and len(vector_obj) == 3:
            if all(isinstance(item, list) and item for item in vector_obj):
                return [SpatialContextLoader._safe_float(item[0]) for item in vector_obj]
            return [SpatialContextLoader._safe_float(item) for item in vector_obj]
        return None

    @staticmethod
    def _apply_rigid_transform(point_xyz: List[float], rotation: List[List[float]], translation: List[float]) -> List[float]:
        x, y, z = point_xyz
        return [
            (rotation[0][0] * x) + (rotation[0][1] * y) + (rotation[0][2] * z) + translation[0],
            (rotation[1][0] * x) + (rotation[1][1] * y) + (rotation[1][2] * z) + translation[1],
            (rotation[2][0] * x) + (rotation[2][1] * y) + (rotation[2][2] * z) + translation[2],
        ]

    @staticmethod
    def _apply_rotation(vec_xyz: List[float], rotation: List[List[float]]) -> List[float]:
        x, y, z = vec_xyz
        return [
            (rotation[0][0] * x) + (rotation[0][1] * y) + (rotation[0][2] * z),
            (rotation[1][0] * x) + (rotation[1][1] * y) + (rotation[1][2] * z),
            (rotation[2][0] * x) + (rotation[2][1] * y) + (rotation[2][2] * z),
        ]

    @staticmethod
    def _normalize_xy(x: float, y: float) -> Tuple[float, float]:
        norm = math.sqrt((x * x) + (y * y))
        if norm <= 1e-8:
            return 1.0, 0.0
        return x / norm, y / norm

    @staticmethod
    def _extract_lane_by_entity(scene_graph_dict: Optional[Dict[str, Any]]) -> Dict[str, str]:
        lane_by_entity: Dict[str, str] = {}
        if not isinstance(scene_graph_dict, dict):
            return lane_by_entity

        for triple in scene_graph_dict.get("object_map_triples", []):
            if not isinstance(triple, dict):
                continue
            relation = str(triple.get("relation", "")).lower()
            if relation != "in":
                continue
            object_type = str(triple.get("object_type", "")).upper()
            if not object_type.startswith("LANE"):
                continue

            subject = str(triple.get("subject", "")).strip()
            lane_id = str(triple.get("object", "")).strip()
            if subject and lane_id:
                lane_by_entity[subject] = lane_id
        return lane_by_entity

    @staticmethod
    def _collect_lane_polygons(
        scene_graph_dict: Optional[Dict[str, Any]],
        map_data: Optional[Dict[str, Any]],
    ) -> Dict[str, List[List[float]]]:
        lane_polygons: Dict[str, List[List[float]]] = {}

        if isinstance(map_data, dict):
            map_lanes = map_data.get("lane")
            if isinstance(map_lanes, dict):
                for lane_id, lane_payload in map_lanes.items():
                    if not isinstance(lane_payload, dict):
                        continue
                    polygon = lane_payload.get("polygon")
                    if not isinstance(polygon, list):
                        continue
                    points: List[List[float]] = []
                    for pt in polygon:
                        if not isinstance(pt, list) or len(pt) < 2:
                            continue
                        points.append([
                            SpatialContextLoader._safe_float(pt[0]),
                            SpatialContextLoader._safe_float(pt[1]),
                        ])
                    if len(points) >= 2:
                        lane_polygons[str(lane_id)] = points

        if isinstance(scene_graph_dict, dict):
            for triple in scene_graph_dict.get("object_map_triples", []):
                if not isinstance(triple, dict):
                    continue
                relation = str(triple.get("relation", "")).lower()
                object_type = str(triple.get("object_type", "")).upper()
                if relation != "in" or not object_type.startswith("LANE"):
                    continue

                lane_id = str(triple.get("object", "")).strip()
                if not lane_id or lane_id in lane_polygons:
                    continue

                obj_meta = triple.get("object_meta")
                if not isinstance(obj_meta, dict):
                    continue
                polygon = obj_meta.get("polygon")
                if not isinstance(polygon, list):
                    continue

                points: List[List[float]] = []
                for pt in polygon:
                    if not isinstance(pt, list) or len(pt) < 2:
                        continue
                    points.append([
                        SpatialContextLoader._safe_float(pt[0]),
                        SpatialContextLoader._safe_float(pt[1]),
                    ])
                if len(points) >= 2:
                    lane_polygons[lane_id] = points

        return lane_polygons

    @staticmethod
    def _lane_axis_from_points(points: List[List[float]]) -> Tuple[float, float, float, float]:
        if not points:
            return 1.0, 0.0, 0.0, 0.0

        cx = sum(p[0] for p in points) / len(points)
        cy = sum(p[1] for p in points) / len(points)

        if len(points) == 1:
            return 1.0, 0.0, cx, cy

        var_x = sum((p[0] - cx) * (p[0] - cx) for p in points)
        var_y = sum((p[1] - cy) * (p[1] - cy) for p in points)
        cov_xy = sum((p[0] - cx) * (p[1] - cy) for p in points)

        theta = 0.5 * math.atan2((2.0 * cov_xy), (var_x - var_y))
        axis_x = math.cos(theta)
        axis_y = math.sin(theta)

        norm = math.sqrt((axis_x * axis_x) + (axis_y * axis_y))
        if norm <= 1e-8:
            first = points[0]
            last = points[-1]
            dx = last[0] - first[0]
            dy = last[1] - first[1]
            alt = math.sqrt((dx * dx) + (dy * dy))
            if alt <= 1e-8:
                return 1.0, 0.0, cx, cy
            return dx / alt, dy / alt, cx, cy

        return axis_x / norm, axis_y / norm, cx, cy

    @staticmethod
    def _build_lane_geometry(
        lane_polygons: Dict[str, List[List[float]]],
        lane_by_entity: Dict[str, str],
        entity_geometry: Dict[str, Dict[str, Any]],
    ) -> Dict[str, Dict[str, float]]:
        lane_geometry: Dict[str, Dict[str, float]] = {}
        for lane_id, points in lane_polygons.items():
            axis_x, axis_y, cx, cy = SpatialContextLoader._lane_axis_from_points(points)

            heading_x = 0.0
            heading_y = 0.0
            heading_count = 0
            for entity_id, mapped_lane in lane_by_entity.items():
                if mapped_lane != lane_id:
                    continue
                geo = entity_geometry.get(entity_id)
                if not isinstance(geo, dict):
                    continue
                heading_x += float(geo.get("heading_x", 0.0))
                heading_y += float(geo.get("heading_y", 0.0))
                heading_count += 1

            if heading_count > 0:
                dot = (axis_x * heading_x) + (axis_y * heading_y)
                if dot < 0.0:
                    axis_x = -axis_x
                    axis_y = -axis_y

            lane_geometry[lane_id] = {
                "axis_x": round(axis_x, 6),
                "axis_y": round(axis_y, 6),
                "center_x": round(cx, 6),
                "center_y": round(cy, 6),
            }

        return lane_geometry

    @staticmethod
    def _backfill_lane_geometry_by_proximity(
        lane_geometry: Dict[str, Dict[str, float]],
        lane_polygons: Dict[str, List[List[float]]],
        lane_by_entity: Dict[str, str],
        entity_geometry: Dict[str, Dict[str, Any]],
        max_center_distance: float = 25.0,
    ) -> int:
        if not lane_polygons or not lane_by_entity or not entity_geometry:
            return 0

        candidate_axes: List[Tuple[str, float, float, float, float]] = []
        for candidate_lane_id, points in lane_polygons.items():
            axis_x, axis_y, center_x, center_y = SpatialContextLoader._lane_axis_from_points(points)
            candidate_axes.append((candidate_lane_id, axis_x, axis_y, center_x, center_y))

        matched_count = 0
        for lane_id in sorted(set(str(lid) for lid in lane_by_entity.values() if str(lid).strip())):
            if lane_id in lane_geometry:
                continue

            members = [entity_id for entity_id, mapped_lane in lane_by_entity.items() if mapped_lane == lane_id]
            if not members:
                continue

            member_points: List[Tuple[float, float]] = []
            heading_x = 0.0
            heading_y = 0.0
            heading_count = 0
            for entity_id in members:
                geo = entity_geometry.get(entity_id)
                if not isinstance(geo, dict):
                    continue
                member_points.append((float(geo.get("x", 0.0)), float(geo.get("y", 0.0))))
                heading_x += float(geo.get("heading_x", 0.0))
                heading_y += float(geo.get("heading_y", 0.0))
                heading_count += 1

            if not member_points:
                continue

            mean_x = sum(p[0] for p in member_points) / len(member_points)
            mean_y = sum(p[1] for p in member_points) / len(member_points)

            best_match: Optional[Tuple[float, float, float, float, float]] = None
            for _candidate_lane_id, axis_x, axis_y, center_x, center_y in candidate_axes:
                dx = center_x - mean_x
                dy = center_y - mean_y
                distance = math.sqrt((dx * dx) + (dy * dy))
                if best_match is None or distance < best_match[0]:
                    best_match = (distance, axis_x, axis_y, center_x, center_y)

            if best_match is None or best_match[0] > max_center_distance:
                continue

            _, axis_x, axis_y, center_x, center_y = best_match
            if heading_count > 0:
                dot = (axis_x * heading_x) + (axis_y * heading_y)
                if dot < 0.0:
                    axis_x = -axis_x
                    axis_y = -axis_y

            lane_geometry[lane_id] = {
                "axis_x": round(axis_x, 6),
                "axis_y": round(axis_y, 6),
                "center_x": round(center_x, 6),
                "center_y": round(center_y, 6),
            }
            matched_count += 1

        return matched_count

    def load(self, frame_id: str, scene_graph_dict: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        label_source = "none"
        label_path = self._frame_file(self.label_virtuallidar_dir, frame_id)
        if label_path:
            label_source = "label_virtuallidar"
        else:
            label_path = self._frame_file(self.label_camera_dir, frame_id)
            if label_path:
                label_source = "label_camera"

        lane_by_entity = self._extract_lane_by_entity(scene_graph_dict)

        map_elements_path = self._frame_file(self.map_elements_dir, frame_id)
        map_data = self._load_json_file(map_elements_path) if map_elements_path else None
        map_available = isinstance(map_data, dict)

        if not label_path:
            lane_polygons = self._collect_lane_polygons(scene_graph_dict, map_data if isinstance(map_data, dict) else None)
            lane_geometry = self._build_lane_geometry(lane_polygons, lane_by_entity, {})
            return {
                "available": False,
                "source": label_source,
                "calibrated_to_world": False,
                "entity_geometry": {},
                "lane_by_entity": lane_by_entity,
                "lane_geometry": lane_geometry,
                "map_elements_file": map_elements_path,
                "map_elements_available": map_available,
                "stats": {
                    "label_count": 0,
                    "geometry_count": 0,
                    "lane_count": len(lane_by_entity),
                    "lane_geometry_count": len(lane_geometry),
                    "lane_geometry_proximity_matches": 0,
                },
            }

        labels = self._load_json_file(label_path)
        if not isinstance(labels, list):
            labels = []

        rotation = None
        translation = None
        calib_path = None
        if label_source == "label_virtuallidar":
            calib_path = self._frame_file(self.calib_virtuallidar_to_world_dir, frame_id)
            if calib_path:
                calib_data = self._load_json_file(calib_path)
                if isinstance(calib_data, dict):
                    rotation = self._parse_rotation_matrix(calib_data.get("rotation"))
                    translation = self._parse_translation_vector(calib_data.get("translation"))

        calibrated_to_world = rotation is not None and translation is not None
        entity_geometry: Dict[str, Dict[str, Any]] = {}

        for item in labels:
            if not isinstance(item, dict):
                continue

            track_id = str(item.get("track_id", "")).strip()
            if not track_id:
                continue

            location = item.get("3d_location")
            if not isinstance(location, dict):
                continue

            px = self._safe_float(location.get("x"))
            py = self._safe_float(location.get("y"))
            pz = self._safe_float(location.get("z"))
            yaw = self._safe_float(item.get("rotation"))

            point = [px, py, pz]
            heading_local = [math.cos(yaw), math.sin(yaw), 0.0]

            if calibrated_to_world and rotation is not None and translation is not None:
                point = self._apply_rigid_transform(point, rotation, translation)
                heading_world = self._apply_rotation(heading_local, rotation)
            else:
                heading_world = heading_local

            heading_x, heading_y = self._normalize_xy(heading_world[0], heading_world[1])
            entity_geometry[track_id] = {
                "x": round(point[0], 6),
                "y": round(point[1], 6),
                "z": round(point[2], 6),
                "heading_x": round(heading_x, 6),
                "heading_y": round(heading_y, 6),
                "yaw": round(yaw, 6),
                "object_type": str(item.get("type", "UNKNOWN")).upper(),
            }

        lane_polygons = self._collect_lane_polygons(scene_graph_dict, map_data if isinstance(map_data, dict) else None)
        lane_geometry = self._build_lane_geometry(lane_polygons, lane_by_entity, entity_geometry)
        proximity_matches = self._backfill_lane_geometry_by_proximity(
            lane_geometry=lane_geometry,
            lane_polygons=lane_polygons,
            lane_by_entity=lane_by_entity,
            entity_geometry=entity_geometry,
        )

        return {
            "available": bool(entity_geometry),
            "source": label_source,
            "calibrated_to_world": calibrated_to_world,
            "calibration_file": calib_path,
            "entity_geometry": entity_geometry,
            "lane_by_entity": lane_by_entity,
            "lane_geometry": lane_geometry,
            "map_elements_file": map_elements_path,
            "map_elements_available": map_available,
            "stats": {
                "label_count": len(labels),
                "geometry_count": len(entity_geometry),
                "lane_count": len(lane_by_entity),
                "lane_geometry_count": len(lane_geometry),
                "lane_geometry_proximity_matches": proximity_matches,
            },
        }
