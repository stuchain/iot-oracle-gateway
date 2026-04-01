"""Tests for telemetry CSV rotation on oracle startup."""

from __future__ import annotations

from pathlib import Path

import oracle.service as svc


def test_rotate_moves_nonempty_csv_to_archive(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(svc, "TELEMETRY_ROTATE_ON_START", True)
    monkeypatch.setattr(svc, "TELEMETRY_ARCHIVE_SUBDIR", "telemetry_archive")
    csv_p = tmp_path / "telemetry_windows.csv"
    csv_p.write_text(
        "window_start_ms,window_end_ms,msg_count,msgs_per_sec,avg_latency_ms,z_score,is_anomaly\n"
        "0,5000,1,0.2,1.0,0.0,0\n",
        encoding="utf-8",
    )
    svc.rotate_telemetry_windows_csv_if_enabled(str(csv_p))
    assert not csv_p.is_file()
    arch_dir = tmp_path / "telemetry_archive"
    assert arch_dir.is_dir()
    archived = list(arch_dir.glob("telemetry_windows_*.csv"))
    assert len(archived) == 1


def test_rotate_noop_when_disabled(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(svc, "TELEMETRY_ROTATE_ON_START", False)
    csv_p = tmp_path / "telemetry_windows.csv"
    csv_p.write_text("x\n", encoding="utf-8")
    svc.rotate_telemetry_windows_csv_if_enabled(str(csv_p))
    assert csv_p.is_file()


def test_rotate_noop_when_file_empty(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(svc, "TELEMETRY_ROTATE_ON_START", True)
    monkeypatch.setattr(svc, "TELEMETRY_ARCHIVE_SUBDIR", "telemetry_archive")
    csv_p = tmp_path / "telemetry_windows.csv"
    csv_p.write_bytes(b"")
    svc.rotate_telemetry_windows_csv_if_enabled(str(csv_p))
    assert csv_p.is_file()
    assert not (tmp_path / "telemetry_archive").exists()
