from __future__ import annotations

from streamlit.testing.v1 import AppTest


def test_app_uses_public_virginia_demo_defaults_in_main_panel() -> None:
    at = AppTest.from_file("app.py")

    at.run()

    text_inputs = {widget.proto.label: widget.value for widget in at.text_input}

    assert len(at.sidebar.text_input) == 0
    assert text_inputs["Origin"] == "Washington, District of Columbia, United States"
    assert text_inputs["Destination"] == "Sacramento, California, United States"
