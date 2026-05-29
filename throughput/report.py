"""Render sweep results into a self-contained HTML report.

No external charting deps: a results table plus inline-SVG bar charts of MB/s
per bucket, so the small-vs-large curve is visible at a glance. Renders any
:class:`ResultSet`, so it works for every tool and for the orchestrator's
combined run.
"""

from __future__ import annotations

import html
from pathlib import Path

from .results import ResultSet


def _svg_bars(rows: list[tuple[str, float]], width: int = 480,
              bar_h: int = 18, gap: int = 6) -> str:
    if not rows:
        return ""
    mx = max((v for _, v in rows), default=0) or 1.0
    label_w, chart_w = 140, width - 160
    height = len(rows) * (bar_h + gap) + gap
    parts = [f'<svg width="{width}" height="{height}" role="img">']
    for i, (label, val) in enumerate(rows):
        y = gap + i * (bar_h + gap)
        w = int(chart_w * (val / mx))
        parts.append(
            f'<text x="0" y="{y + bar_h - 4}" font-size="12">{html.escape(label)}</text>'
            f'<rect x="{label_w}" y="{y}" width="{w}" height="{bar_h}" fill="#3b82f6"/>'
            f'<text x="{label_w + w + 4}" y="{y + bar_h - 4}" font-size="11">{val:g}</text>'
        )
    parts.append("</svg>")
    return "".join(parts)


def render_html(results: ResultSet, *, title: str = "Throughput report") -> str:
    by_group: dict[tuple[str, str], list] = {}
    for r in results:
        by_group.setdefault((r.tool, r.operation), []).append(r)

    sections = []
    for (tool, op), items in sorted(by_group.items()):
        items = sorted(items, key=lambda r: r.size_bytes)
        bars = _svg_bars([(r.bucket, r.mb_per_s) for r in items])
        trows = "".join(
            f"<tr><td>{html.escape(r.bucket)}</td><td>{r.mb_per_s:g}</td>"
            f"<td>{r.ops_per_s:g}</td><td>{r.ops}</td>"
            f"<td>{round(r.seconds, 3)}</td></tr>"
            for r in items
        )
        sections.append(
            f"<h2>{html.escape(tool)} — {html.escape(op)}</h2>"
            f'<div class="chart">{bars}</div>'
            "<table><thead><tr><th>bucket</th><th>MB/s</th><th>ops/s</th>"
            f"<th>ops</th><th>sec</th></tr></thead><tbody>{trows}</tbody></table>"
        )

    body = "\n".join(sections) if sections else "<p>No results.</p>"
    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<title>{html.escape(title)}</title>
<style>
 body{{font-family:system-ui,sans-serif;margin:2rem;color:#111}}
 h1{{margin-bottom:.2rem}} h2{{margin-top:2rem}}
 table{{border-collapse:collapse;margin-top:.5rem}}
 th,td{{border:1px solid #ddd;padding:4px 10px;text-align:right}}
 th:first-child,td:first-child{{text-align:left}}
 .chart{{margin:.5rem 0}}
</style></head>
<body><h1>{html.escape(title)}</h1>
<p>{len(results)} measurement(s).</p>
{body}
</body></html>"""


def write_report(results: ResultSet, path: str | Path, *,
                 title: str = "Throughput report") -> Path:
    path = Path(path)
    path.write_text(render_html(results, title=title))
    return path
