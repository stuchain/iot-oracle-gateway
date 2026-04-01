"""Logic tests for dashboard helper functions with Streamlit stubs."""

from __future__ import annotations

import importlib
import io
import sys
import types
import zipfile
from pathlib import Path


class _Ctx:
    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False


class _State(dict):
    def __getattr__(self, name):
        return self.get(name)

    def __setattr__(self, name, value):
        self[name] = value


def _build_streamlit_stub():
    mod = types.ModuleType("streamlit")
    mod.session_state = _State()
    mod.sidebar = _Ctx()
    mod.set_page_config = lambda *a, **k: None
    mod.title = lambda *a, **k: None
    mod.caption = lambda *a, **k: None
    mod.header = lambda *a, **k: None
    mod.subheader = lambda *a, **k: None
    mod.write = lambda *a, **k: None
    mod.metric = lambda *a, **k: None
    mod.markdown = lambda *a, **k: None
    mod.line_chart = lambda *a, **k: None
    mod.success = lambda *a, **k: None
    mod.toast = lambda *a, **k: None
    mod.warning = lambda *a, **k: None
    mod.info = lambda *a, **k: None
    mod.error = lambda *a, **k: None
    mod.text_input = lambda *a, **k: ""
    mod.number_input = lambda *a, **k: k.get("value", 0)
    mod.checkbox = lambda *a, **k: k.get("value", False)
    mod.button = lambda *a, **k: False

    def _selectbox(*args, **kwargs):
        opts = kwargs.get("options")
        if opts is None and len(args) > 1:
            opts = args[1]
        idx = kwargs.get("index", 0)
        if isinstance(opts, list) and opts:
            return opts[idx] if idx < len(opts) else opts[0]
        return None

    mod.selectbox = _selectbox
    mod.download_button = lambda *a, **k: None
    mod.rerun = lambda *a, **k: None
    mod.columns = lambda n, *a, **k: [_Ctx() for _ in range(n)]
    return mod


def _import_dashboard_app(monkeypatch):
    st_mod = _build_streamlit_stub()
    autoref_mod = types.ModuleType("streamlit_autorefresh")
    autoref_mod.st_autorefresh = lambda *a, **k: None
    req_mod = types.ModuleType("requests")

    class _Resp:
        status_code = 200

        @staticmethod
        def json():
            return {}

    req_mod.RequestException = Exception
    req_mod.get = lambda *a, **k: _Resp()

    monkeypatch.setitem(sys.modules, "streamlit", st_mod)
    monkeypatch.setitem(sys.modules, "streamlit_autorefresh", autoref_mod)
    monkeypatch.setitem(sys.modules, "requests", req_mod)

    if "dashboard.app" in sys.modules:
        del sys.modules["dashboard.app"]
    return importlib.import_module("dashboard.app")


def test_load_sim_config_missing_file_returns_empty(monkeypatch, tmp_path):
    app = _import_dashboard_app(monkeypatch)
    app.SIM_CONFIG_PATH = tmp_path / "missing.json"
    assert app.load_sim_config() == {}


def test_load_sim_config_invalid_json_returns_empty(monkeypatch, tmp_path):
    app = _import_dashboard_app(monkeypatch)
    p = tmp_path / "bad.json"
    p.write_text("{not-json", encoding="utf-8")
    app.SIM_CONFIG_PATH = p
    assert app.load_sim_config() == {}


def test_save_sim_config_creates_parent_and_writes_sorted_json(monkeypatch, tmp_path):
    app = _import_dashboard_app(monkeypatch)
    p = tmp_path / "nested" / "sim_config.json"
    app.SIM_CONFIG_PATH = p
    app.save_sim_config({"B": 2, "A": 1})
    raw = p.read_text(encoding="utf-8")
    assert '"A": 1' in raw
    assert '"B": 2' in raw
    assert raw.endswith("\n")


def test_fetch_metrics_http_non_200_returns_error(monkeypatch):
    app = _import_dashboard_app(monkeypatch)

    class _Resp:
        status_code = 503

        @staticmethod
        def json():
            return {}

    app.requests.get = lambda *a, **k: _Resp()
    data, err = app.fetch_metrics()
    assert data is None
    assert "HTTP 503" in (err or "")


def test_fetch_metrics_request_exception_returns_error(monkeypatch):
    app = _import_dashboard_app(monkeypatch)

    def _raise(*_a, **_k):
        raise app.requests.RequestException("boom")

    app.requests.get = _raise
    data, err = app.fetch_metrics()
    assert data is None
    assert err == "Cannot reach oracle endpoint. Check service and network."


def test_load_telemetry_csv_missing_required_columns_returns_error(monkeypatch, tmp_path):
    app = _import_dashboard_app(monkeypatch)
    p = tmp_path / "telemetry_windows.csv"
    p.write_text("window_end_ms,msgs_per_sec\n1000,1.0\n", encoding="utf-8")
    monkeypatch.setenv("TELEMETRY_CSV_PATH", str(p))
    df, err = app.load_telemetry_csv()
    assert df is None
    assert "missing columns" in (err or "").lower()


def test_load_telemetry_csv_missing_file_redacts_absolute_path(monkeypatch, tmp_path):
    app = _import_dashboard_app(monkeypatch)
    missing = tmp_path / "not_there.csv"
    monkeypatch.setenv("TELEMETRY_CSV_PATH", str(missing))
    df, err = app.load_telemetry_csv()
    assert df is None
    assert err == "Telemetry CSV not found. Run the oracle or set TELEMETRY_CSV_PATH."
    assert str(missing) not in (err or "")


def test_load_telemetry_csv_empty_file_returns_empty_df_no_error(monkeypatch, tmp_path):
    app = _import_dashboard_app(monkeypatch)
    p = tmp_path / "telemetry_windows.csv"
    p.write_text("window_end_ms,msgs_per_sec,z_score\n", encoding="utf-8")
    monkeypatch.setenv("TELEMETRY_CSV_PATH", str(p))
    df, err = app.load_telemetry_csv()
    assert err is None
    assert df is not None
    assert df.empty


def test_telemetry_csv_path_prefers_override_then_data_dir(monkeypatch):
    app = _import_dashboard_app(monkeypatch)
    monkeypatch.setenv("TELEMETRY_CSV_PATH", "x/y.csv")
    assert str(app.telemetry_csv_path()).replace("\\", "/").endswith("x/y.csv")
    monkeypatch.delenv("TELEMETRY_CSV_PATH", raising=False)
    monkeypatch.setenv("DATA_DIR", "custom_data")
    assert Path("custom_data/telemetry_windows.csv").as_posix() in str(
        app.telemetry_csv_path()
    ).replace("\\", "/")


def test_build_results_export_zip_contains_metrics_and_artifacts(monkeypatch, tmp_path):
    app = _import_dashboard_app(monkeypatch)
    sim = tmp_path / "sim_config.json"
    sim.write_text('{"N_DEVICES": 2}', encoding="utf-8")
    tel = tmp_path / "telemetry_windows.csv"
    tel.write_text("window_end_ms,msgs_per_sec,z_score\n1000,1.0,0\n", encoding="utf-8")
    anch = tmp_path / "anchoring_log.csv"
    anch.write_text("timestamp_iso,batch_hash,success\n", encoding="utf-8")
    metrics = {
        "verified_count": 1,
        "last_anchor_info": {
            "batch_hash": "0xabc",
            "tx_hash": "0xdef",
            "success": True,
        },
    }
    zbytes, name = app.build_results_export_zip(
        metrics,
        sim_config_path=sim,
        telemetry_csv_path_override=tel,
        anchoring_log_path_override=anch,
        deployment_json_override=tmp_path / "missing_deploy.json",
        anchor_txt_override=tmp_path / "missing_anchor_txt",
    )
    assert name.startswith("iot-oracle-export-") and name.endswith(".zip")
    zf = zipfile.ZipFile(io.BytesIO(zbytes))
    names = zf.namelist()
    assert "metrics.json" in names
    assert "sim_config.json" in names
    assert "telemetry_windows.csv" in names
    assert "anchoring_log.csv" in names
    assert "export_manifest.json" in names
    inner = zf.read("metrics.json").decode("utf-8")
    assert "0xabc" in inner and "last_anchor_info" in inner


def test_list_telemetry_session_files_includes_current_and_archives(monkeypatch, tmp_path):
    app = _import_dashboard_app(monkeypatch)
    data = tmp_path / "data"
    data.mkdir()
    current = data / "telemetry_windows.csv"
    current.write_text("window_end_ms,msgs_per_sec,z_score\n", encoding="utf-8")
    arch = data / "telemetry_archive"
    arch.mkdir()
    old = arch / "telemetry_windows_20250101T120000Z.csv"
    old.write_text("window_end_ms,msgs_per_sec,z_score\n5000,1,0\n", encoding="utf-8")
    monkeypatch.setenv("DATA_DIR", "data")
    monkeypatch.delenv("TELEMETRY_CSV_PATH", raising=False)
    app._REPO_ROOT = tmp_path
    entries = app.list_telemetry_session_files()
    assert len(entries) >= 2
    assert entries[0][0] == "Current (active)"
    assert entries[0][1] == current
    names = [e[0] for e in entries]
    assert "telemetry_windows_20250101T120000Z.csv" in names


def test_open_past_sessions_folder_creates_archive_and_returns_none(monkeypatch, tmp_path):
    app = _import_dashboard_app(monkeypatch)
    monkeypatch.setenv("DATA_DIR", "data")
    app._REPO_ROOT = tmp_path
    opened = []

    def _fake_popen(cmd, **_k):
        opened.append(cmd)

    monkeypatch.setattr("subprocess.Popen", _fake_popen)
    err = app.open_past_sessions_folder()
    assert err is None
    assert (tmp_path / "data" / "telemetry_archive").is_dir()
    assert opened


def test_load_telemetry_csv_accepts_explicit_path(monkeypatch, tmp_path):
    app = _import_dashboard_app(monkeypatch)
    p = tmp_path / "other.csv"
    p.write_text("window_end_ms,msgs_per_sec,z_score\n1000,1.0,0\n", encoding="utf-8")
    df, err = app.load_telemetry_csv(p)
    assert err is None
    assert df is not None
    assert len(df) == 1
