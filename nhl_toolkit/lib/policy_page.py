"""
Renders docs/policy.html: a quick-reference page showing every metric in
policy.yaml, its weight, its normalization method, and (where available)
its description/unit from the metrics catalog. This is a read-only view
for tuning weights, not a data output -- edit policy.yaml and re-run
score.py to actually change scoring.

Regenerated automatically by run_daily.py, or run standalone:

Usage:
    python lib/policy_page.py
"""

import sqlite3
from pathlib import Path
from typing import Optional

from db import get_connection
from report import DOCS_DIR, HTML_STYLE
from score import POLICY_PATH, load_policy


def load_metric_metadata(conn: sqlite3.Connection) -> dict[str, tuple]:
    """Look up each metric's description/unit from the metrics catalog.

    :param conn: Open connection to the schedule database.
    :returns: Mapping of metric name to (description, unit); empty if the
        metrics table hasn't been seeded yet (run metrics.py first).
    """
    try:
        rows = conn.execute("SELECT name, description, unit FROM metrics").fetchall()
    except sqlite3.OperationalError:
        return {}
    return {name: (description, unit) for name, description, unit in rows}


def render_policy_html(policy: dict, metadata: dict[str, tuple]) -> Path:
    """Render the current policy as a static HTML reference page.

    :param policy: Parsed policy config, as returned by :func:`score.load_policy`.
    :param metadata: Metric name -> (description, unit), from :func:`load_metric_metadata`.
    :returns: Path to the written HTML file.
    """
    DOCS_DIR.mkdir(parents=True, exist_ok=True)

    def format_weight(weight: float) -> str:
        css_class = "positive" if weight >= 0 else "negative"
        return f'<span class="{css_class}">{weight:+.2f}</span>'

    rows = "\n".join(
        f"""
        <tr>
            <td>{name}</td>
            <td class="notes">{metadata.get(name, ("", ""))[0] or "&mdash;"}</td>
            <td class="notes">{metadata.get(name, ("", ""))[1] or "&mdash;"}</td>
            <td>{format_weight(cfg["weight"])}</td>
            <td>{cfg["normalize"]}</td>
        </tr>"""
        for name, cfg in policy["metrics"].items()
    )

    page = f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>NHL Scoring Policy</title>
<meta name="viewport" content="width=device-width, initial-scale=1">
<style>{HTML_STYLE}</style>
</head>
<body>
<p><a href="index.html">&larr; All reports</a></p>
<h1>Scoring Policy</h1>
<p class="subtitle">
Version <strong>{policy["policy_version"]}</strong> &middot;
edit nhl_toolkit/policy.yaml to change weights, then re-run score.py
</p>
<table>
<thead>
<tr><th>Metric</th><th>Description</th><th>Unit</th><th>Weight</th><th>Normalize</th></tr>
</thead>
<tbody>{rows}
</tbody>
</table>
<p class="disclaimer">
Positive weights push a team's score up; negative weights pull it down.
Each metric's raw value is normalized (see the Normalize column) across
that day's slate before the weight is applied, so metrics on different
scales combine fairly.
</p>
</body>
</html>
"""
    path = DOCS_DIR / "policy.html"
    with open(path, "w") as f:
        f.write(page)
    return path


def build_policy_page(policy_path: Optional[Path] = None) -> Path:
    """Load the current policy and metric metadata, then render the policy page.

    :param policy_path: Optional override for the policy YAML file location.
    :returns: Path to the written HTML file.
    """
    policy = load_policy(policy_path or POLICY_PATH)
    conn = get_connection()
    metadata = load_metric_metadata(conn)
    conn.close()
    path = render_policy_html(policy, metadata)
    print(f"Wrote {path}")
    return path


if __name__ == "__main__":
    build_policy_page()
