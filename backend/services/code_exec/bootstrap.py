"""Bootstrap prologue/epilogue injected around user Python code."""

from __future__ import annotations

import json
import textwrap

META_SENTINEL = "__VELA_EXEC_META__"


def build_python_script(
    user_code: str,
    *,
    workspace_root: str,
    state_file: str,
    state_persist: bool,
    show_counter_start: int = 0,
) -> str:
    """Wrap user code with interpreter bootstrap."""
    root = workspace_root.replace("\\", "\\\\")
    state = state_file.replace("\\", "\\\\")
    persist = "True" if state_persist else "False"

    prologue = textwrap.dedent(f'''
        import sys
        import os
        import json
        import traceback

        _VELA_WORKSPACE = r"{root}"
        _VELA_STATE_FILE = r"{state}"
        _VELA_STATE_PERSIST = {persist}
        _VELA_SHOW_COUNTER = [{show_counter_start}]
        _VELA_META = {{"state_saved": 0, "state_skipped": 0, "plots_saved": []}}

        os.chdir(_VELA_WORKSPACE)
        sys.path.insert(0, _VELA_WORKSPACE)

        # matplotlib: Agg backend + auto-save on show()
        try:
            import matplotlib
            matplotlib.use("Agg")
            import matplotlib.pyplot as _plt

            def _vela_show(*args, **kwargs):
                _VELA_SHOW_COUNTER[0] += 1
                out_dir = os.path.join(_VELA_WORKSPACE, "outputs")
                os.makedirs(out_dir, exist_ok=True)
                fname = f"plot_{{_VELA_SHOW_COUNTER[0]:03d}}.png"
                fpath = os.path.join(out_dir, fname)
                _plt.savefig(fpath, bbox_inches="tight", dpi=120)
                _VELA_META["plots_saved"].append(fname)
                _plt.close("all")

            _plt.show = _vela_show
        except Exception:
            pass

        # pandas display settings
        try:
            import pandas as _pd
            _pd.set_option("display.max_rows", 200)
            _pd.set_option("display.max_columns", 50)
            _pd.set_option("display.width", 200)
            _pd.set_option("display.max_colwidth", 80)
        except Exception:
            pass

        # restore persisted globals
        if _VELA_STATE_PERSIST and os.path.isfile(_VELA_STATE_FILE):
            try:
                try:
                    import dill as _pickle_mod
                except ImportError:
                    import pickle as _pickle_mod
                with open(_VELA_STATE_FILE, "rb") as _sf:
                    _restored = _pickle_mod.load(_sf)
                if isinstance(_restored, dict):
                    globals().update(_restored)
            except Exception as _restore_err:
                print(f"[vela] 状态恢复失败: {{_restore_err}}", file=sys.stderr)

        def _vela_excepthook(exc_type, exc_val, exc_tb):
            lines = traceback.format_exception(exc_type, exc_val, exc_tb)
            filtered = []
            skip = False
            for line in lines:
                if "<string>" in line or "run_" in line:
                    skip = False
                if "bootstrap" in line.lower() or "_vela_" in line.lower():
                    continue
                filtered.append(line)
            sys.stderr.write("".join(filtered))
            sys.stderr.flush()

        sys.excepthook = _vela_excepthook
    ''')

    epilogue = textwrap.dedent('''
        # save persisted globals
        if _VELA_STATE_PERSIST:
            _skip_names = {
                "__builtins__", "__name__", "__doc__", "__package__",
                "__loader__", "__spec__", "__annotations__", "__cached__",
            }
            _to_save = {}
            for _k, _v in list(globals().items()):
                if _k.startswith("_") or _k in _skip_names:
                    continue
                try:
                    try:
                        import dill as _pickle_mod
                    except ImportError:
                        import pickle as _pickle_mod
                    _pickle_mod.dumps(_v)
                    _to_save[_k] = _v
                    _VELA_META["state_saved"] += 1
                except Exception:
                    _VELA_META["state_skipped"] += 1
            if _to_save:
                os.makedirs(os.path.dirname(_VELA_STATE_FILE), exist_ok=True)
                try:
                    import dill as _pickle_mod
                except ImportError:
                    import pickle as _pickle_mod
                with open(_VELA_STATE_FILE, "wb") as _sf:
                    _pickle_mod.dump(_to_save, _sf)

        print("__VELA_EXEC_META__" + json.dumps(_VELA_META, ensure_ascii=False))
    ''')

    return prologue + "\n" + user_code + "\n" + epilogue


def parse_meta_from_stdout(stdout: str) -> tuple[str, dict | None]:
    """Strip sentinel JSON line from stdout; return cleaned stdout and meta."""
    lines = stdout.splitlines()
    meta = None
    cleaned: list[str] = []
    for line in lines:
        if line.startswith(META_SENTINEL):
            try:
                meta = json.loads(line[len(META_SENTINEL):])
            except json.JSONDecodeError:
                pass
        else:
            cleaned.append(line)
    return "\n".join(cleaned).strip(), meta
