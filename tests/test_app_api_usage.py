from __future__ import annotations

import ast
from pathlib import Path


def test_app_avoids_deprecated_streamlit_use_container_width_calls() -> None:
    source = Path("app.py").read_text(encoding="utf-8")
    tree = ast.parse(source)
    offending_calls: list[str] = []

    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        if not isinstance(node.func, ast.Attribute):
            continue
        if not isinstance(node.func.value, ast.Name) or node.func.value.id != "st":
            continue

        for keyword in node.keywords:
            if keyword.arg == "use_container_width":
                offending_calls.append(node.func.attr)

    assert offending_calls == []
