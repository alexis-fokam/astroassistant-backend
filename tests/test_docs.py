"""Dictionnaire de données : chaque colonne documentée, chaque table rendue."""

from app.docs.dictionary import DOMAINS, build, table_domain, table_models
from app.models import Base


def test_every_column_has_a_description() -> None:
    missing = [
        f"{table.name}.{column.name}"
        for table in Base.metadata.sorted_tables
        for column in table.columns
        if not (column.comment or "").strip()
    ]
    assert missing == []


def test_every_table_has_a_docstring_and_a_domain() -> None:
    domains = {key for key, _, _ in DOMAINS}
    for name, model in table_models().items():
        assert (model.__doc__ or "").strip(), name
        assert table_domain(model) in domains, name


def test_dictionary_renders_every_table() -> None:
    counts = {t.name: 0 for t in Base.metadata.sorted_tables}
    text = build(counts)
    for table in Base.metadata.sorted_tables:
        assert f"### `{table.name}`" in text
    assert "POSTCOMPILE" not in text
    assert "erDiagram" in text
