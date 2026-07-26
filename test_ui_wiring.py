"""
test_ui_wiring.py — static wiring check for Gradio handlers.

Builds the Blocks app without launching a server, iterates over every registered
event dependency, and compares the number of input components with the Python
function signature. Mismatches fail with the function name and the expected /
actual counts.

Run: python test_ui_wiring.py
"""

import inspect
import sys


def _signature_accepts(signature: inspect.Signature, n: int) -> bool:
    """Return True if the function can be called with exactly *n* positional args."""
    params = list(signature.parameters.values())
    min_args = 0
    max_args = 0
    has_var_positional = False
    for p in params:
        if p.kind in (p.POSITIONAL_ONLY, p.POSITIONAL_OR_KEYWORD):
            max_args += 1
            if p.default is inspect.Parameter.empty:
                min_args += 1
        elif p.kind == p.VAR_POSITIONAL:
            has_var_positional = True
    if has_var_positional:
        return n >= min_args
    return min_args <= n <= max_args


def _collect_dependencies(app) -> list:
    """Return the list of event dependencies from a Gradio Blocks app."""
    # Gradio 4.x stores dependencies in multiple places depending on the version.
    if hasattr(app, "dependencies") and app.dependencies:
        return app.dependencies
    if hasattr(app, "fns") and app.fns:
        return app.fns
    return []


def main() -> int:
    # Import after ensuring the project root is on sys.path
    import os
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

    try:
        import gradio  # noqa: F401
    except ImportError as exc:
        print(f"SKIP: gradio is not installed in this environment ({exc}).")
        print("This test requires gradio (e.g. pip install gradio==4.44.0).")
        return 0

    if not hasattr(gradio, "Blocks"):
        print("SKIP: gradio is installed but does not expose gr.Blocks (incomplete/broken install).")
        print("This test requires a working gradio installation (e.g. pip install gradio==4.44.0).")
        return 0

    from gradio_app import build_app

    app = build_app()
    # Force Gradio to populate the dependency list
    if hasattr(app, "render"):
        app.render()

    dependencies = _collect_dependencies(app)
    if not dependencies:
        print("SKIP: no dependencies found on the Blocks app")
        return 0

    failures = []
    for dep in dependencies:
        fn = dep.get("fn") if isinstance(dep, dict) else getattr(dep, "fn", None)
        if fn is None:
            continue
        if not callable(fn):
            continue

        sig = inspect.signature(fn)
        # JS-only handlers (no Python fn) are skipped above.
        # Compare the number of registered inputs with the signature.
        inputs = dep.get("inputs", []) if isinstance(dep, dict) else getattr(dep, "inputs", [])
        input_count = len(inputs)
        func_name = getattr(fn, "__name__", repr(fn))

        if not _signature_accepts(sig, input_count):
            params = list(sig.parameters.values())
            min_args = sum(1 for p in params if p.default is inspect.Parameter.empty and p.kind in (p.POSITIONAL_ONLY, p.POSITIONAL_OR_KEYWORD))
            max_args = len([p for p in params if p.kind in (p.POSITIONAL_ONLY, p.POSITIONAL_OR_KEYWORD)])
            has_var = any(p.kind == p.VAR_POSITIONAL for p in params)
            failures.append(
                f"{func_name}: inputs={input_count}, signature accepts "
                f"{min_args if not has_var else f'{min_args}+'}"
                f"{'..*' if has_var else f'..{max_args}'}"
            )

    if failures:
        print("FAILURES — Gradio input counts do not match handler signatures:")
        for msg in failures:
            print(f"  - {msg}")
        return 1

    print(f"OK — {len(dependencies)} handler(s) wired, all input counts match signatures.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
