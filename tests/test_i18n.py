from __future__ import annotations

from src.i18n import t


def test_translations_return_spanish_and_english_values() -> None:
    assert t("es", "ui.generate_routes") == "Buscar rutas alternativas"
    assert t("en", "ui.generate_routes") == "Get route alternatives"


def test_translations_support_formatting_placeholders() -> None:
    assert (
        t("en", "analysis.routes_found", count=3)
        == "The routing service returned 3 candidate routes. Choose one route and evaluate it over the time window."
    )


def test_spanish_reverse_geocode_warning_is_human_readable() -> None:
    assert (
        t("es", "picker.reverse_geocode_warning")
        == "No se pudo obtener el nombre exacto del punto. Se usará el texto escrito o las coordenadas."
    )
