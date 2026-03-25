#!/usr/bin/env python3
"""Generate throughput and z-score PNGs from oracle telemetry_windows.csv.

Reads CSV on each invocation (no caching). Typical usage from repo root::

    python scripts/plot_results.py
    python scripts/plot_results.py --csv data/telemetry_windows.csv --output-dir plots --z-threshold 3.0
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import pandas as pd


def _time_series(df: pd.DataFrame) -> tuple[pd.Series, str]:
    if "window_end_ms" in df.columns:
        t = pd.to_datetime(df["window_end_ms"], unit="ms", utc=True)
        return t, "window_end_ms"
    if "window_start_ms" in df.columns:
        t = pd.to_datetime(df["window_start_ms"], unit="ms", utc=True)
        return t, "window_start_ms"
    raise ValueError("CSV must include window_end_ms or window_start_ms")


def main() -> int:
    parser = argparse.ArgumentParser(description="Plot msgs_per_sec and z_score from telemetry CSV.")
    parser.add_argument(
        "--csv",
        type=Path,
        default=Path("data/telemetry_windows.csv"),
        help="Path to telemetry_windows.csv (default: data/telemetry_windows.csv)",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("plots"),
        help="Directory for PNG output (default: plots)",
    )
    parser.add_argument(
        "--z-threshold",
        type=float,
        default=3.0,
        help="Horizontal line on z-score plot (default: 3.0)",
    )
    args = parser.parse_args()

    csv_path = args.csv
    if not csv_path.is_file():
        print(f"Error: CSV not found: {csv_path.resolve()}", file=sys.stderr)
        return 1

    try:
        df = pd.read_csv(csv_path)
    except Exception as e:
        print(f"Error reading CSV: {e}", file=sys.stderr)
        return 1

    out_dir = args.output_dir
    out_dir.mkdir(parents=True, exist_ok=True)

    if df.empty:
        fig, ax = plt.subplots(figsize=(10, 4))
        ax.set_title("Throughput (msgs/s) over time — no rows in CSV")
        ax.text(0.5, 0.5, "No data", ha="center", va="center", transform=ax.transAxes)
        fig.savefig(out_dir / "throughput.png", dpi=150, bbox_inches="tight")
        plt.close(fig)

        fig, ax = plt.subplots(figsize=(10, 4))
        ax.set_title("Z-score over time — no rows in CSV")
        ax.text(0.5, 0.5, "No data", ha="center", va="center", transform=ax.transAxes)
        fig.savefig(out_dir / "z_score.png", dpi=150, bbox_inches="tight")
        plt.close(fig)
        print(f"Wrote empty plots to {out_dir.resolve()} (CSV had no rows).")
        return 0

    required = {"msgs_per_sec", "z_score"}
    missing = required - set(df.columns)
    if missing:
        print(f"Error: CSV missing columns: {sorted(missing)}", file=sys.stderr)
        return 1

    try:
        times, tname = _time_series(df)
    except ValueError as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1

    # Throughput
    fig, ax = plt.subplots(figsize=(10, 4))
    ax.plot(times, df["msgs_per_sec"], marker="o", markersize=3)
    ax.set_xlabel(f"Time (UTC, from {tname})")
    ax.set_ylabel("msgs_per_sec")
    ax.set_title("Throughput (msgs/s) over time")
    fig.autofmt_xdate()
    fig.savefig(out_dir / "throughput.png", dpi=150, bbox_inches="tight")
    plt.close(fig)

    # Z-score + threshold
    fig, ax = plt.subplots(figsize=(10, 4))
    ax.plot(times, df["z_score"], marker="o", markersize=3, label="z_score", color="C0")
    ax.axhline(
        args.z_threshold,
        color="red",
        linestyle="--",
        linewidth=1.5,
        label=f"Z_THRESHOLD = {args.z_threshold}",
    )
    ax.set_xlabel(f"Time (UTC, from {tname})")
    ax.set_ylabel("z_score")
    ax.set_title("Z-score over time")
    ax.legend(loc="best")
    fig.autofmt_xdate()
    fig.savefig(out_dir / "z_score.png", dpi=150, bbox_inches="tight")
    plt.close(fig)

    print(f"Wrote {out_dir.resolve() / 'throughput.png'}")
    print(f"Wrote {out_dir.resolve() / 'z_score.png'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
