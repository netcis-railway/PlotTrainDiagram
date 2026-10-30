"""Isolated, headless process for registered, locally maintained plotting code."""

import importlib
import json
import sys
from contextlib import redirect_stdout
from pathlib import Path


def main():
    request = json.load(sys.stdin)
    try:
        with redirect_stdout(sys.stderr):
            module = importlib.import_module("app.solver_visualizers." + request["module"])
            function = getattr(module, request["function"])
            result = function(
                Path(request["input_path"]),
                Path(request["output_dir"]),
                request["filename"],
                request["options"],
            )
        print(json.dumps({"ok": True, **result}, ensure_ascii=True, allow_nan=False))
    except Exception as error:
        print(json.dumps({"ok": False, "error": str(error)}, ensure_ascii=True))


if __name__ == "__main__":
    main()
