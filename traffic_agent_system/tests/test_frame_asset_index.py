import os
import tempfile
import unittest

from core.frame_asset_index import FrameAssetIndexer


class TestFrameAssetIndexer(unittest.TestCase):
    def test_frame_alignment_and_summary(self):
        with tempfile.TemporaryDirectory() as tmp:
            sg_dir = os.path.join(tmp, "sg")
            bev_dir = os.path.join(tmp, "bev")
            raw_dir = os.path.join(tmp, "raw")
            os.makedirs(sg_dir, exist_ok=True)
            os.makedirs(bev_dir, exist_ok=True)
            os.makedirs(raw_dir, exist_ok=True)

            open(os.path.join(sg_dir, "000001_scene_graph.json"), "w", encoding="utf-8").close()
            open(os.path.join(sg_dir, "000002_scene_graph.json"), "w", encoding="utf-8").close()
            open(os.path.join(bev_dir, "000001_intersection.png"), "w", encoding="utf-8").close()
            open(os.path.join(raw_dir, "000001.jpg"), "w", encoding="utf-8").close()
            open(os.path.join(raw_dir, "000002.jpg"), "w", encoding="utf-8").close()

            indexer = FrameAssetIndexer(sg_dir, bev_dir, raw_dir)

            assets_000001 = indexer.get_frame_assets("000001")
            assets_000002 = indexer.get_frame_assets("000002")
            summary = indexer.get_summary()

            self.assertTrue(assets_000001["is_complete"])
            self.assertFalse(assets_000002["is_complete"])
            self.assertEqual(summary["scene_graph_frames"], 2)
            self.assertEqual(summary["bev_frames"], 1)
            self.assertEqual(summary["raw_frames"], 2)
            self.assertEqual(summary["complete_frames"], 1)


if __name__ == "__main__":
    unittest.main()
