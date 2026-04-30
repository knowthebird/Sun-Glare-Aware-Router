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


def test_app_uses_two_panel_layout_with_stacked_pickers() -> None:
    source = Path("app.py").read_text(encoding="utf-8")

    assert "left_panel, right_panel = st.columns([1, 1])" in source
    assert "with right_panel:" in source
    assert 'title=t(language, "picker.origin")' in source
    assert 'title=t(language, "picker.destination")' in source
    assert "controls_col1, controls_col2, controls_col3 = st.columns(" in source


def test_app_uses_forms_so_enter_submits_picker_searches() -> None:
    source = Path("app.py").read_text(encoding="utf-8")

    assert 'with st.form(f"{picker_kind}_search_form"):' in source
    assert 'st.form_submit_button(t(language, "picker.search")' in source


def test_app_renders_comparison_table_below_both_columns() -> None:
    source = Path("app.py").read_text(encoding="utf-8")

    assert "def render_comparison_table(" in source
    assert "render_comparison_table(saved_result_to_render, language)" in source


def test_app_injects_shared_styles_for_a_cleaner_layout() -> None:
    source = Path("app.py").read_text(encoding="utf-8")

    assert "def inject_app_styles() -> None:" in source
    assert "sunrouter-shell" in source
    assert "inject_app_styles()" in source


def test_app_defines_language_state_and_translation_usage() -> None:
    source = Path("app.py").read_text(encoding="utf-8")

    assert 'LANGUAGE_STATE_KEY = "sunrouter_language"' in source
    assert 'st.session_state[LANGUAGE_STATE_KEY] = "es"' in source
    assert "from src.i18n import t" in source


def test_app_uses_column_config_for_consistent_comparison_widths() -> None:
    source = Path("app.py").read_text(encoding="utf-8")

    assert "column_config={" in source
    assert "st.column_config.TextColumn(" in source
