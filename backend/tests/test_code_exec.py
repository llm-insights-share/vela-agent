"""Tests for Code Interpreter sandbox."""

import asyncio
import os
import tempfile
import uuid

import pytest

from services.code_exec.bootstrap import build_python_script, parse_meta_from_stdout
from services.code_exec.workspace import SessionWorkspace


@pytest.fixture
def session_output_dir():
    session_id = f"test_{uuid.uuid4().hex[:8]}"
    base = os.path.join(
        os.path.dirname(os.path.dirname(__file__)),
        "data", "outputs", session_id,
    )
    os.makedirs(base, exist_ok=True)
    yield base
    # cleanup
    ws = SessionWorkspace.from_output_dir(base)
    import shutil
    if ws.root.exists():
        shutil.rmtree(ws.root, ignore_errors=True)
    if os.path.isdir(base):
        shutil.rmtree(base, ignore_errors=True)


@pytest.mark.asyncio
async def test_simple_python_execution(session_output_dir):
    from services.code_exec.runner import run_code

    result = await run_code(
        'print("hello sandbox")\nx = 42\nprint(x)',
        session_output_dir,
        language="python",
        timeout=30,
    )
    assert result["success"] is True
    assert "hello sandbox" in result.get("stdout", "")
    assert "42" in result.get("stdout", "")


@pytest.mark.asyncio
async def test_state_persistence_across_calls(session_output_dir):
    from services.code_exec.runner import run_code

    r1 = await run_code('counter = 1\nprint(counter)', session_output_dir)
    assert r1["success"] is True

    r2 = await run_code('counter += 1\nprint(counter)', session_output_dir)
    assert r2["success"] is True
    assert "2" in r2.get("stdout", "")


@pytest.mark.asyncio
async def test_execution_error_returns_traceback(session_output_dir):
    from services.code_exec.runner import run_code

    result = await run_code('1/0', session_output_dir)
    assert result["success"] is False
    assert "ZeroDivisionError" in (result.get("error") or "")


@pytest.mark.asyncio
async def test_env_secrets_not_visible(session_output_dir):
    os.environ["VELA_TEST_SECRET_XYZ"] = "super-secret-value-12345"
    try:
        from services.code_exec.runner import run_code

        result = await run_code(
            'import os\nprint(os.environ.get("VELA_TEST_SECRET_XYZ", "MISSING"))',
            session_output_dir,
        )
        assert result["success"] is True
        assert "MISSING" in result.get("stdout", "")
        assert "super-secret" not in result.get("stdout", "")
    finally:
        os.environ.pop("VELA_TEST_SECRET_XYZ", None)


@pytest.mark.asyncio
async def test_artifact_detection(session_output_dir):
    from services.code_exec.runner import run_code

    result = await run_code(
        'open("outputs/test_out.txt", "w").write("artifact content")',
        session_output_dir,
    )
    assert result["success"] is True
    artifacts = result.get("artifacts") or []
    names = [a.get("name") for a in artifacts]
    assert "test_out.txt" in names


@pytest.mark.asyncio
async def test_output_truncation(session_output_dir):
    from services.code_exec.config import load_code_exec_config, save_code_exec_config, CodeExecConfig
    from services.code_exec.runner import run_code

    cfg = load_code_exec_config()
    orig_max = cfg.max_output_bytes
    try:
        cfg.max_output_bytes = 200
        save_code_exec_config(cfg)
        result = await run_code('print("x" * 500)', session_output_dir)
        assert result["success"] is True
        assert result.get("output_truncated") or len(result.get("stdout", "")) <= 200
    finally:
        cfg.max_output_bytes = orig_max
        save_code_exec_config(cfg)


def test_parse_meta_from_stdout():
    stdout = "hello\n__VELA_EXEC_META__{\"state_saved\": 1}"
    cleaned, meta = parse_meta_from_stdout(stdout)
    assert cleaned == "hello"
    assert meta["state_saved"] == 1


def test_workspace_snapshot_diff():
    with tempfile.TemporaryDirectory() as tmp:
        ws = SessionWorkspace("snap_test")
        ws.root = __import__("pathlib").Path(tmp)
        ws.outputs = ws.root / "outputs"
        ws.outputs.mkdir(parents=True)
        before = ws.snapshot()
        (ws.outputs / "new_file.csv").write_text("a,b\n1,2")
        after = ws.snapshot()
        arts = ws.sweep_artifacts(before, after)
        assert any(a["name"] == "new_file.csv" for a in arts)


def test_build_python_script_contains_bootstrap():
    script = build_python_script(
        "print(1)",
        workspace_root="/tmp/ws",
        state_file="/tmp/ws/.state/globals.pkl",
        state_persist=True,
    )
    assert "matplotlib" in script
    assert "__VELA_EXEC_META__" in script
    assert "print(1)" in script
