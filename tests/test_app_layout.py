from __future__ import annotations

from streamlit.testing.v1 import AppTest


def _expander_labels(at: AppTest) -> list[str]:
    labels: list[str] = []
    for expander in at.expander:
        label = getattr(expander, "label", None)
        if isinstance(label, str):
            labels.append(label)
            continue
        proto_label = getattr(getattr(expander, "proto", None), "label", None)
        if isinstance(proto_label, str):
            labels.append(proto_label)
    return labels


def test_app_renders_information_and_main_panel_controls() -> None:
    at = AppTest.from_file("app.py")

    at.run()

    markdown_text = " ".join(item.value for item in at.markdown)
    warning_text = " ".join(item.value for item in at.warning)
    button_labels = [getattr(button.proto, "label", "") for button in at.button]
    subheaders = [item.value for item in at.subheader]

    assert "Information" in _expander_labels(at)
    assert "glare risk" in markdown_text.lower()
    assert "how it works" in markdown_text.lower()
    assert "limitations" in markdown_text.lower()
    assert "not a driving-safety guarantee" in warning_text
    assert len(at.sidebar.text_input) == 0
    assert "Origin" in subheaders
    assert "Destination" in subheaders
    assert "Get route alternatives" in button_labels
    assert "Reverse origin and destination" in button_labels


def test_app_defaults_to_english_language_selector() -> None:
    at = AppTest.from_file("app.py")

    at.run()

    radio_values = {
        getattr(widget.proto, "label", ""): widget.value for widget in at.radio
    }

    assert radio_values["Idioma / Language"] == "EN"


def test_generate_routes_is_enabled_for_the_first_run_demo_trip() -> None:
    at = AppTest.from_file("app.py")

    at.run()

    generate_button = next(
        button
        for button in at.button
        if getattr(button.proto, "label", "") == "Get route alternatives"
    )

    assert generate_button.proto.disabled is False
