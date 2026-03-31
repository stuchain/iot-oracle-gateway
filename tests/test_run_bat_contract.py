"""Contract test for run.bat bootstrap wiring."""

from __future__ import annotations

from pathlib import Path


def test_run_bat_invokes_start_stack_powershell_script():
    root = Path(__file__).resolve().parents[1]
    run_bat = root / "run.bat"
    text = run_bat.read_text(encoding="utf-8")
    assert "powershell -NoProfile -ExecutionPolicy Bypass -File" in text
    assert "scripts\\start_stack.ps1" in text
