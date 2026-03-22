"""Lightweight check that dashboard app source is valid (no Streamlit runtime required)."""

import py_compile
from pathlib import Path


def test_dashboard_app_py_compiles():
    root = Path(__file__).resolve().parents[1]
    path = root / "dashboard" / "app.py"
    assert path.is_file()
    py_compile.compile(str(path), doraise=True)
