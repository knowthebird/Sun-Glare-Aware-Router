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
    button_labels = [getattr(button.proto, "label", "") for button in at.button]
    subheaders = [item.value for item in at.subheader]

    assert "Información" in _expander_labels(at)
    assert "riesgo de deslumbramiento" in markdown_text.lower()
    assert "cómo funciona" in markdown_text.lower()
    assert "limitaciones" in markdown_text.lower()
    assert len(at.sidebar.text_input) == 0
    assert "Origen" in subheaders
    assert "Destino" in subheaders
    assert "Generar rutas" in button_labels


def test_app_defaults_to_spanish_language_selector() -> None:
    at = AppTest.from_file("app.py")

    at.run()

    radio_values = {
        getattr(widget.proto, "label", ""): widget.value for widget in at.radio
    }

    assert radio_values["Idioma / Language"] == "ES"


def test_generate_routes_is_disabled_until_both_points_are_confirmed() -> None:
    at = AppTest.from_file("app.py")

    at.run()

    generate_button = next(
        button
        for button in at.button
        if getattr(button.proto, "label", "") == "Generar rutas"
    )

    assert generate_button.proto.disabled is True
