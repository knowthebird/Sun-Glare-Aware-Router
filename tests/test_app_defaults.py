from __future__ import annotations

from datetime import time

from streamlit.testing.v1 import AppTest


def test_app_uses_madrid_to_burgos_defaults_in_main_panel() -> None:
    at = AppTest.from_file("app.py")

    at.run()

    text_inputs = {widget.proto.label: widget.value for widget in at.text_input}
    time_inputs = {widget.proto.label: widget.value for widget in at.time_input}
    selectboxes = {widget.proto.label: widget.value for widget in at.selectbox}

    assert len(at.sidebar.text_input) == 0
    assert text_inputs["Origen"] == "Madrid, Spain"
    assert text_inputs["Destino"] == "Burgos, Spain"
    assert time_inputs["Hora"] == time(hour=9, minute=0)
    assert selectboxes["Zona horaria"] == "Europe/Madrid"
