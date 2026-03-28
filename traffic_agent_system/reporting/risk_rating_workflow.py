import json
import os
from datetime import datetime
from html import escape
from typing import Any, Dict, List


class RiskRatingWorkflow:
    """Generate structured and human-friendly risk rating artifacts from pipeline outputs."""

    def __init__(self, output_dir: str):
        self.output_dir = output_dir

    @staticmethod
    def _risk(record: Dict[str, Any]) -> Dict[str, Any]:
        return ((record.get("event_analysis") or {}).get("risk") or {})

    @staticmethod
    def _risk_level(record: Dict[str, Any]) -> str:
        return str(RiskRatingWorkflow._risk(record).get("level", "low"))

    @staticmethod
    def _risk_score(record: Dict[str, Any]) -> int:
        return int(RiskRatingWorkflow._risk(record).get("score", 0))

    @staticmethod
    def _overall_rating(risk_levels: Dict[str, int], processed: int) -> Dict[str, Any]:
        high = int(risk_levels.get("high", 0))
        medium = int(risk_levels.get("medium", 0))
        low = int(risk_levels.get("low", 0))
        weighted = high * 3 + medium * 2 + low * 1
        max_weighted = max(1, processed * 3)
        normalized = round((weighted / max_weighted) * 100, 2)

        if normalized >= 65 or high >= max(3, processed // 5):
            level = "A"
            cn_label = "高风险"
        elif normalized >= 35 or medium >= max(3, processed // 4):
            level = "B"
            cn_label = "中风险"
        else:
            level = "C"
            cn_label = "低风险"

        return {
            "grade": level,
            "label": cn_label,
            "score_0_100": normalized,
            "high_rate": round((high / processed), 4) if processed else 0.0,
            "medium_rate": round((medium / processed), 4) if processed else 0.0,
        }

    @staticmethod
    def _recommendations(grade: str, event_segment_count: int) -> List[str]:
        if grade == "A":
            return [
                "建议立即对高风险时段进行信号配时优化与冲突点复核。",
                "建议优先排查持续性冲突链与死锁段，必要时增加临时管控策略。",
                "建议将高风险片段纳入人工抽检与回放复盘清单。",
            ]
        if grade == "B":
            base = [
                "建议对中高风险帧进行抽样复核，确认让行关系是否稳定。",
                "建议针对高频冲突路口进行局部参数调优并持续观察。",
            ]
            if event_segment_count > 0:
                base.append("建议对事件段峰值帧进行专题复盘，避免风险段扩展。")
            return base
        return [
            "当前风险总体可控，建议保持轻量化监控与周期性巡检。",
            "建议保留自动化评分流程，作为后续数据扩展时的基线。",
        ]

    def _build_structured_payload(
        self,
        summary: Dict[str, Any],
        records: List[Dict[str, Any]],
        event_segments: List[Dict[str, Any]],
        review_mode: str,
    ) -> Dict[str, Any]:
        processed = int(summary.get("processed", 0))
        risk_levels = summary.get("risk_levels", {}) if isinstance(summary.get("risk_levels"), dict) else {}
        overall = self._overall_rating(risk_levels, processed)
        top_records = sorted(records, key=self._risk_score, reverse=True)[:20]

        top_risk_frames: List[Dict[str, Any]] = []
        for rec in top_records:
            event_analysis = rec.get("event_analysis") or {}
            top_risk_frames.append(
                {
                    "frame_id": rec.get("frame_id"),
                    "risk_level": self._risk_level(rec),
                    "risk_score": self._risk_score(rec),
                    "fast_decision": event_analysis.get("fast_decision", ""),
                    "dominant_causes": [
                        cause
                        for cause in [
                            "yielding_disorder" if int((self._risk(rec)).get("yielding_cnt", 0)) > 0 else "",
                            "conflict_chain" if int((self._risk(rec)).get("chain_cnt", 0)) > 0 else "",
                            "deadlock" if int((self._risk(rec)).get("deadlock_cnt", 0)) > 0 else "",
                            "following_cycle" if bool((self._risk(rec)).get("cycle_detected", False)) else "",
                            "following_bottleneck"
                            if int((self._risk(rec)).get("bottleneck_cnt", 0)) > 0
                            or int((self._risk(rec)).get("max_chain", 0)) >= 4
                            else "",
                        ]
                        if cause
                    ],
                    "assets": rec.get("assets", {}),
                }
            )

        return {
            "meta": {
                "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                "workflow": "risk_rating_workflow",
                "review_mode": review_mode,
            },
            "run": {
                "jsonl": summary.get("output_file", ""),
                "summary_json": summary.get("summary_file", ""),
                "processed": processed,
                "skipped": int(summary.get("skipped", 0)),
            },
            "risk_distribution": {
                "high": int(risk_levels.get("high", 0)),
                "medium": int(risk_levels.get("medium", 0)),
                "low": int(risk_levels.get("low", 0)),
            },
            "overall_rating": overall,
            "event_segment_count": len(event_segments),
            "event_segments": event_segments,
            "top_risk_frames": top_risk_frames,
            "recommendations": self._recommendations(overall["grade"], len(event_segments)),
        }

    @staticmethod
    def _write_json(path: str, payload: Dict[str, Any]) -> None:
        with open(path, "w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False, indent=2)

    @staticmethod
    def _build_markdown(payload: Dict[str, Any], path: str) -> None:
        lines: List[str] = []
        lines.append("# 交叉口风险评级报告")
        lines.append("")
        lines.append("## 总体评级")
        overall = payload.get("overall_rating", {})
        lines.append(f"- 等级: {overall.get('grade', '-')} ({overall.get('label', '-')})")
        lines.append(f"- 综合分: {overall.get('score_0_100', 0)} / 100")
        lines.append(f"- 高风险占比: {overall.get('high_rate', 0)}")
        lines.append(f"- 中风险占比: {overall.get('medium_rate', 0)}")
        lines.append("")
        lines.append("## 风险分布")
        risk = payload.get("risk_distribution", {})
        lines.append(f"- 高风险帧: {risk.get('high', 0)}")
        lines.append(f"- 中风险帧: {risk.get('medium', 0)}")
        lines.append(f"- 低风险帧: {risk.get('low', 0)}")
        lines.append(f"- 事件段数量: {payload.get('event_segment_count', 0)}")
        lines.append("")

        lines.append("## 重点风险帧 (Top 20)")
        top_frames = payload.get("top_risk_frames", [])
        if top_frames:
            for item in top_frames:
                lines.append(
                    "- frame={frame_id}, level={risk_level}, score={risk_score}, causes=[{causes}]".format(
                        frame_id=item.get("frame_id"),
                        risk_level=item.get("risk_level"),
                        risk_score=item.get("risk_score"),
                        causes=", ".join(item.get("dominant_causes", [])),
                    )
                )
        else:
            lines.append("- 无可用帧记录")
        lines.append("")

        lines.append("## 治理建议")
        for rec in payload.get("recommendations", []):
            lines.append(f"- {rec}")
        lines.append("")

        lines.append("## 模式")
        lines.append(f"- 当前模式: {payload.get('meta', {}).get('review_mode', 'manual')}")

        with open(path, "w", encoding="utf-8") as f:
            f.write("\n".join(lines))

    @staticmethod
    def _build_html(payload: Dict[str, Any], path: str) -> None:
        overall = payload.get("overall_rating", {})
        risk = payload.get("risk_distribution", {})
        rows = []
        for item in payload.get("top_risk_frames", []):
            rows.append(
                "<tr>"
                f"<td>{escape(str(item.get('frame_id', '-')))}</td>"
                f"<td>{escape(str(item.get('risk_level', '-')))}</td>"
                f"<td>{escape(str(item.get('risk_score', '-')))}</td>"
                f"<td>{escape(', '.join(item.get('dominant_causes', [])))}</td>"
                f"<td>{escape(str(item.get('fast_decision', '')))}</td>"
                "</tr>"
            )

        recs = "".join(f"<li>{escape(str(r))}</li>" for r in payload.get("recommendations", []))

        html = f"""
<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>交叉口风险评级报告</title>
  <style>
    body {{ margin: 0; padding: 24px; font-family: "Segoe UI", "Noto Sans SC", "Microsoft YaHei", sans-serif; background: #f3f6fb; color: #0f172a; }}
    .wrap {{ max-width: 1100px; margin: 0 auto; }}
    .panel {{ background: #fff; border: 1px solid #d8e0ec; border-radius: 12px; padding: 14px; margin-bottom: 14px; }}
    .cards {{ display: grid; grid-template-columns: repeat(4, minmax(140px, 1fr)); gap: 10px; }}
    .card {{ background: #f8fafc; border: 1px solid #e2e8f0; border-radius: 10px; padding: 10px; }}
    .label {{ color: #64748b; font-size: 12px; font-weight: 700; }}
    .value {{ margin-top: 4px; font-size: 24px; font-weight: 800; color: #0f766e; }}
    table {{ width: 100%; border-collapse: collapse; }}
    th, td {{ border-bottom: 1px solid #e2e8f0; text-align: left; padding: 8px; font-size: 13px; vertical-align: top; }}
    th {{ background: #eef2ff; }}
  </style>
</head>
<body>
  <div class="wrap">
    <div class="panel">
      <h1>交叉口风险评级报告</h1>
      <p>模式: {escape(str(payload.get('meta', {}).get('review_mode', 'manual')))}</p>
      <div class="cards">
        <div class="card"><div class="label">综合等级</div><div class="value">{escape(str(overall.get('grade', '-')))}</div></div>
        <div class="card"><div class="label">综合得分</div><div class="value">{escape(str(overall.get('score_0_100', 0)))}</div></div>
        <div class="card"><div class="label">高风险帧</div><div class="value">{escape(str(risk.get('high', 0)))}</div></div>
        <div class="card"><div class="label">事件段</div><div class="value">{escape(str(payload.get('event_segment_count', 0)))}</div></div>
      </div>
    </div>

    <div class="panel">
      <h2>治理建议</h2>
      <ul>{recs}</ul>
    </div>

    <div class="panel">
      <h2>重点风险帧</h2>
      <table>
        <thead>
          <tr><th>Frame</th><th>Level</th><th>Score</th><th>Dominant Causes</th><th>Fast Decision</th></tr>
        </thead>
        <tbody>
          {''.join(rows) if rows else '<tr><td colspan="5">无可用帧记录</td></tr>'}
        </tbody>
      </table>
    </div>
  </div>
</body>
</html>
"""

        with open(path, "w", encoding="utf-8") as f:
            f.write(html)

    def build(
        self,
        summary: Dict[str, Any],
        records: List[Dict[str, Any]],
        event_segments: List[Dict[str, Any]],
        review_mode: str,
        auto_human_report: bool,
    ) -> Dict[str, str]:
        os.makedirs(self.output_dir, exist_ok=True)
        output_file = str(summary.get("output_file", "run.jsonl"))
        stem = os.path.splitext(os.path.basename(output_file))[0]

        structured_json = os.path.join(self.output_dir, f"{stem}_risk_rating_structured.json")
        payload = self._build_structured_payload(summary, records, event_segments, review_mode=review_mode)
        self._write_json(structured_json, payload)

        result = {
            "structured_json": structured_json,
        }

        if auto_human_report:
            markdown_path = os.path.join(self.output_dir, f"{stem}_risk_rating_report.md")
            html_path = os.path.join(self.output_dir, f"{stem}_risk_rating_report.html")
            self._build_markdown(payload, markdown_path)
            self._build_html(payload, html_path)
            result["markdown"] = markdown_path
            result["html"] = html_path

        return result
