"""plot_results.py produces PNGs from a small CSV."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]


def test_plot_results_writes_non_empty_pngs(tmp_path):
    csv_path = tmp_path / "telemetry_windows.csv"
    csv_path.write_text(
        "window_start_ms,window_end_ms,msg_count,msgs_per_sec,avg_latency_ms,z_score,is_anomaly\n"
        "0,5000,5,1.0,10.0,0.1,0\n"
        "5000,10000,40,8.0,12.0,4.5,1\n"
        "10000,15000,5,1.0,11.0,0.2,0\n",
        encoding="utf-8",
    )
    out_dir = tmp_path / "plots"
    script = REPO_ROOT / "scripts" / "plot_results.py"
    r = subprocess.run(
        [
            sys.executable,
            str(script),
            "--csv",
            str(csv_path),
            "--output-dir",
            str(out_dir),
            "--z-threshold",
            "3.0",
        ],
        cwd=str(REPO_ROOT),
        capture_output=True,
        text=True,
    )
    assert r.returncode == 0, r.stderr + r.stdout
    tp = out_dir / "throughput.png"
    zp = out_dir / "z_score.png"
    assert tp.is_file() and tp.stat().st_size > 100
    assert zp.is_file() and zp.stat().st_size > 100
