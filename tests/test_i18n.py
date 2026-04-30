from __future__ import annotations

from src.i18n import t


def test_translations_return_spanish_and_english_values() -> None:
    assert t("es", "ui.generate_routes") == "Generar rutas"
    assert t("en", "ui.generate_routes") == "Generate routes"


def test_translations_support_formatting_placeholders() -> None:
    assert (
        t("en", "analysis.routes_found", count=3)
        == "The routing service returned 3 candidate routes. All of them are shown on the map and the recommended one is highlighted."
    )
