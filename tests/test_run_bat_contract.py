"""Contract tests for one-click launcher wiring."""

from __future__ import annotations

from pathlib import Path


def test_run_bat_invokes_start_stack_powershell_script():
    root = Path(__file__).resolve().parents[1]
    run_bat = root / "run.bat"
    text = run_bat.read_text(encoding="utf-8")
    assert "powershell -NoProfile -ExecutionPolicy Bypass -File" in text
    assert "scripts\\start_stack.ps1" in text


def test_start_stack_uses_contracts_working_directory_for_hardhat_node():
    root = Path(__file__).resolve().parents[1]
    script = (root / "scripts" / "start_stack.ps1").read_text(encoding="utf-8")
    assert "-WorkingDirectory $contractsDir" in script
    assert "node `\"$hardhatCli`\" node --hostname 127.0.0.1 --port 8545" in script


def test_start_stack_has_readiness_loops_and_port_preflight_checks():
    root = Path(__file__).resolve().parents[1]
    script = (root / "scripts" / "start_stack.ps1").read_text(encoding="utf-8")
    assert "function Wait-JsonRpcReady" in script
    assert "function Wait-HttpReady" in script
    assert "function Assert-StartupPortsAvailable" in script
    assert "Wait-JsonRpcReady -Url $rpcUrl" in script
    assert "Wait-HttpReady -Url 'http://127.0.0.1:8000/metrics'" in script
    assert "Wait-HttpReady -Url 'http://127.0.0.1:8501'" in script
    assert "Skipping oracle start because healthy service is already running on :8000." in script
    assert "Skipping dashboard start because healthy service is already running on :8501." in script
    assert "Skipping Mosquitto start because :1883 is already in use." in script


def test_stop_bat_invokes_stop_stack_powershell_script():
    root = Path(__file__).resolve().parents[1]
    stop_bat = root / "stop.bat"
    text = stop_bat.read_text(encoding="utf-8")
    assert "powershell -NoProfile -ExecutionPolicy Bypass -File" in text
    assert "scripts\\stop_stack.ps1" in text


def test_stop_stack_script_targets_stack_ports():
    root = Path(__file__).resolve().parents[1]
    script = (root / "scripts" / "stop_stack.ps1").read_text(encoding="utf-8")
    assert "$StackPorts = @(8545, 1883, 8000, 8501)" in script
    assert "function Get-ListeningPidsForPort" in script
    assert "Stop-Process" in script
