import os
from html import escape
from typing import Any, Dict, List


class ReviewReportBuilder:
    """Build markdown/html reports from pipeline outputs."""

    def __init__(self, output_dir: str):
        self.output_dir = output_dir

    @staticmethod
    def _risk_score(record: Dict[str, Any]) -> int:
        event_analysis = record.get("event_analysis") or {}
        risk = event_analysis.get("slowdown") or event_analysis.get("risk") or {}
        return int(risk.get("score", 0))

    @staticmethod
    def _risk_level(record: Dict[str, Any]) -> str:
        event_analysis = record.get("event_analysis") or {}
        risk = event_analysis.get("slowdown") or event_analysis.get("risk") or {}
        return str(risk.get("level", "low"))

    @staticmethod
    def _slowdown_class(record: Dict[str, Any]) -> str:
        event_analysis = record.get("event_analysis") or {}
        risk = event_analysis.get("slowdown") or event_analysis.get("risk") or {}
        return str(risk.get("class", "normal_controlled_queue"))

    @staticmethod
    def _to_relative_path(base_dir: str, target_path: str) -> str:
        if not target_path:
            return ""
        rel = os.path.relpath(target_path, start=base_dir)
        return rel.replace("\\", "/")

    def _build_markdown(
        self,
        summary: Dict[str, Any],
        records: List[Dict[str, Any]],
        event_segments: List[Dict[str, Any]],
        output_path: str,
    ) -> None:
        top_records = sorted(records, key=self._risk_score, reverse=True)[:10]
        levels = summary.get("slowdown_levels") or summary.get("risk_levels") or {}

        lines: List[str] = []
        lines.append("# Traffic Slow-Queue Run Summary")
        lines.append("")
        lines.append("## Overview")
        lines.append(f"- Processed frames: {summary.get('processed', 0)}")
        lines.append(f"- Skipped frames: {summary.get('skipped', 0)}")
        lines.append(f"- Event segments: {len(event_segments)}")
        lines.append("")

        lines.append("## Slowdown Distribution")
        lines.append(f"- Severe Slowdown: {levels.get('high', 0)}")
        lines.append(f"- Moderate Slowdown: {levels.get('medium', 0)}")
        lines.append(f"- Light/No Slowdown: {levels.get('low', 0)}")
        lines.append("")

        lines.append("## Event Segments")
        if event_segments:
            for seg in event_segments:
                causes = ", ".join(seg.get("dominant_causes", []))
                lines.append(
                    "- Segment #{sid}: {start} -> {end}, peak={peak_frame}(score={peak_score}), causes=[{causes}]".format(
                        sid=seg.get("segment_id"),
                        start=seg.get("start_frame"),
                        end=seg.get("end_frame"),
                        peak_frame=seg.get("peak_frame"),
                        peak_score=seg.get("peak_score"),
                        causes=causes,
                    )
                )
        else:
            lines.append("- No moderate/severe slowdown segment detected.")
        lines.append("")

        lines.append("## Top Slowdown Frames")
        if top_records:
            for rec in top_records:
                lines.append(
                  "- frame={fid}, level={lvl}, class={clazz}, score={score}".format(
                        fid=rec.get("frame_id"),
                        lvl=self._risk_level(rec),
                    clazz=self._slowdown_class(rec),
                        score=self._risk_score(rec),
                    )
                )
        else:
            lines.append("- No records available.")
        lines.append("")

        lines.append("## Output Files")
        lines.append(f"- JSONL: {summary.get('output_file', '')}")
        lines.append(f"- Summary JSON: {summary.get('summary_file', '')}")

        with open(output_path, "w", encoding="utf-8") as f:
            f.write("\n".join(lines))

    def _build_html(
        self,
        summary: Dict[str, Any],
        records: List[Dict[str, Any]],
        event_segments: List[Dict[str, Any]],
        output_path: str,
    ) -> None:
        top_records = sorted(records, key=self._risk_score, reverse=True)[:20]
        base_dir = os.path.dirname(output_path)
        levels = summary.get("slowdown_levels") or summary.get("risk_levels") or {}

        segment_rows: List[str] = []
        for seg in event_segments:
            segment_rows.append(
                "<tr>"
                f"<td>{seg.get('segment_id')}</td>"
                f"<td>{escape(str(seg.get('start_frame')))} -> {escape(str(seg.get('end_frame')))}</td>"
                f"<td>{escape(str(seg.get('peak_frame')))}</td>"
                f"<td>{seg.get('peak_score')}</td>"
                f"<td>{escape(', '.join(seg.get('dominant_causes', [])))}</td>"
                "</tr>"
            )

        frame_rows: List[str] = []
        for rec in top_records:
            assets = rec.get("assets", {})
            raw_rel = self._to_relative_path(base_dir, assets.get("raw_image") or "")
            bev_rel = self._to_relative_path(base_dir, assets.get("bev_image") or "")
            sg_rel = self._to_relative_path(base_dir, assets.get("scene_graph_json") or "")

            raw_html = f'<img src="{escape(raw_rel)}" alt="raw" class="thumb" />' if raw_rel else "-"
            bev_html = f'<img src="{escape(bev_rel)}" alt="bev" class="thumb" />' if bev_rel else "-"
            sg_html = f'<a href="{escape(sg_rel)}">scene_graph.json</a>' if sg_rel else "-"

            frame_rows.append(
                "<tr>"
                f"<td>{escape(str(rec.get('frame_id')))}</td>"
                f"<td>{escape(self._risk_level(rec))}</td>"
              f"<td>{escape(self._slowdown_class(rec))}</td>"
                f"<td>{self._risk_score(rec)}</td>"
                f"<td>{raw_html}</td>"
                f"<td>{bev_html}</td>"
                f"<td>{sg_html}</td>"
                "</tr>"
            )

        html = f"""
<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>Traffic Slow-Queue Review</title>
  <style>
    :root {{
      --bg: #f5f6f8;
      --card: #ffffff;
      --ink: #1f2937;
      --muted: #6b7280;
      --line: #d1d5db;
      --accent: #0f766e;
    }}
    body {{
      margin: 0;
      padding: 24px;
      background: var(--bg);
      color: var(--ink);
      font-family: "Segoe UI", "Noto Sans", sans-serif;
    }}
    .wrap {{
      max-width: 1200px;
      margin: 0 auto;
    }}
    .header {{
      margin-bottom: 18px;
    }}
    .cards {{
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(180px, 1fr));
      gap: 12px;
      margin-bottom: 18px;
    }}
    .card {{
      background: var(--card);
      border: 1px solid var(--line);
      border-radius: 12px;
      padding: 12px;
    }}
    .label {{ color: var(--muted); font-size: 12px; }}
    .value {{ font-size: 24px; font-weight: 700; color: var(--accent); }}
    .panel {{
      background: var(--card);
      border: 1px solid var(--line);
      border-radius: 12px;
      padding: 12px;
      margin-bottom: 16px;
      overflow: auto;
    }}
    table {{ width: 100%; border-collapse: collapse; min-width: 840px; }}
    th, td {{ border-bottom: 1px solid var(--line); padding: 8px; text-align: left; vertical-align: top; }}
    th {{ background: #eef2ff; }}
    .thumb {{ width: 220px; height: auto; border: 1px solid var(--line); border-radius: 8px; }}
    h1, h2 {{ margin: 10px 0; }}
  </style>
</head>
<body>
  <div class="wrap">
    <div class="header">
      <h1>Traffic Slow-Queue Review</h1>
      <p>JSONL: {escape(str(summary.get("output_file", "")))}</p>
    </div>

    <div class="cards">
      <div class="card"><div class="label">Processed</div><div class="value">{summary.get("processed", 0)}</div></div>
      <div class="card"><div class="label">Severe Slowdown Frames</div><div class="value">{levels.get("high", 0)}</div></div>
      <div class="card"><div class="label">Event Segments</div><div class="value">{len(event_segments)}</div></div>
      <div class="card"><div class="label">Pruning Ratio</div><div class="value">{round(((summary.get("global_pruning") or {}).get("compression_ratio", 0.0)) * 100, 2)}%</div></div>
    </div>

    <div class="panel">
      <h2>Temporal Slowdown Segments</h2>
      <table>
        <thead>
          <tr>
            <th>ID</th><th>Range</th><th>Peak Frame</th><th>Peak Score</th><th>Dominant Causes</th>
          </tr>
        </thead>
        <tbody>
          {''.join(segment_rows) if segment_rows else '<tr><td colspan="5">No moderate/severe slowdown segment detected.</td></tr>'}
        </tbody>
      </table>
    </div>

    <div class="panel">
      <h2>Top Slowdown Frames (Raw + BEV + SG)</h2>
      <table>
        <thead>
          <tr>
            <th>Frame</th><th>Level</th><th>Class</th><th>Score</th><th>Raw Image</th><th>BEV</th><th>Scene Graph</th>
          </tr>
        </thead>
        <tbody>
          {''.join(frame_rows) if frame_rows else '<tr><td colspan="7">No records available.</td></tr>'}
        </tbody>
      </table>
    </div>
  </div>
</body>
</html>
"""

        with open(output_path, "w", encoding="utf-8") as f:
            f.write(html)

    def build(
        self,
        summary: Dict[str, Any],
        records: List[Dict[str, Any]],
        event_segments: List[Dict[str, Any]],
    ) -> Dict[str, str]:
        os.makedirs(self.output_dir, exist_ok=True)
        output_file = str(summary.get("output_file", "run.jsonl"))
        stem = os.path.splitext(os.path.basename(output_file))[0]

        markdown_path = os.path.join(self.output_dir, f"{stem}_summary.md")
        html_path = os.path.join(self.output_dir, f"{stem}_review.html")

        self._build_markdown(summary, records, event_segments, markdown_path)
        self._build_html(summary, records, event_segments, html_path)

        return {
            "markdown": markdown_path,
            "html": html_path,
        }
