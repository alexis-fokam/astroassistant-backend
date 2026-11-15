"""Générer le dictionnaire de données (Markdown, en français) depuis les métadonnées SQLAlchemy.

Tout vient des modèles eux-mêmes : descriptions des tables depuis les docstrings des classes,
descriptions des colonnes depuis ``comment=``, types, clés, contraintes et index depuis les
métadonnées, et nombres de lignes depuis une base de démo neuve en mémoire. Lancer
``python -m app.docs`` après chaque changement de modèle pour que le document reste à jour.
"""

from __future__ import annotations

import inspect as pyinspect
from collections import defaultdict
from datetime import datetime
from enum import StrEnum

from sqlalchemy import (
    CheckConstraint,
    Column,
    Enum,
    Table,
    UniqueConstraint,
    create_engine,
    event,
    func,
    select,
)
from sqlalchemy.dialects import sqlite
from sqlalchemy.orm import Session

from app.models import Base

# Domaines fonctionnels, dans l'ordre de lecture. Clé = nom du module de modèles.
DOMAINS: list[tuple[str, str, str]] = [
    ("mission", "Mission", "Paramètres de la mission (A-03)."),
    ("crew", "Équipage et capteurs", "Profils locaux, capteurs appairés et baselines (F1, F7)."),
    ("vitals", "Télémétrie et check-in", "Constantes physiologiques et auto-déclaration (F1, F3)."),
    ("wellness", "Bien-être", "Exercice, sommeil, vigilance et nutrition (F6, F7, F8)."),
    ("radiation", "Radiations", "Météo spatiale et dosimétrie individuelle (F5)."),
    ("datasets", "Données ouvertes", "Provenance et mesures réelles NASA/NOAA (§12)."),
    ("scoring", "Moteur IA", "Indicateurs calculés et scores de risque (F2)."),
    ("alerts", "Alertes et urgences", "Alertes cliniques et mode urgence (F2, F9, F12)."),
    ("protocols", "Protocoles", "Bibliothèque de contre-mesures et exécutions (F4)."),
    ("medical", "Médecine de bord", "Journal médical et pharmacie (F9, F11)."),
    ("sync", "Liaison sol", "Export différé, consignes et fenêtres de contact (F10)."),
    ("audit", "Audit", "Journal non modifiable chaîné par SHA-256 (F14)."),
    ("simulation", "Simulation", "Scénarios S1 à S6 et exécutions du simulateur (F15)."),
]

ON_DELETE = {
    "CASCADE": "suppression en cascade",
    "SET NULL": "mise à NULL",
    "RESTRICT": "suppression interdite",
    None: "suppression interdite (par défaut)",
}


def table_models() -> dict[str, type]:
    return {m.local_table.name: m.class_ for m in Base.registry.mappers}


def table_domain(model: type) -> str:
    return model.__module__.rsplit(".", 1)[-1]


def describe(model: type) -> str:
    return pyinspect.cleandoc(model.__doc__ or "").strip()


def column_type(col: Column) -> str:
    if isinstance(col.type, Enum) and col.type.enum_class is not None:
        return f"VARCHAR({col.type.length}) · `{col.type.enum_class.__name__}`"
    compiled = col.type.compile(dialect=sqlite.dialect())
    return compiled.replace("DATETIME", "DATETIME (UTC)")


def column_default(col: Column) -> str:
    default = col.default
    if default is None:
        return ""
    arg = default.arg
    if callable(arg):
        name = getattr(arg, "__name__", "")
        return {"utcnow": "maintenant (UTC)", "dict": "`{}`", "list": "`[]`"}.get(
            name.split(".")[-1], f"`{name}()`"
        )
    if isinstance(arg, StrEnum):
        return f"`{arg.value}`"
    if isinstance(arg, bool):
        return "vrai" if arg else "faux"
    return f"`{arg}`"


def column_keys(col: Column, table: Table) -> str:
    keys = []
    if col.primary_key:
        keys.append("PK")
    for fk in col.foreign_keys:
        keys.append(f"FK → `{fk.column.table.name}.{fk.column.name}`")
    unique_cols = {
        tuple(c.name for c in u.columns)
        for u in table.constraints
        if isinstance(u, UniqueConstraint)
    }
    if col.unique or (col.name,) in unique_cols:
        keys.append("UNIQUE")
    if col.index:
        keys.append("IDX")
    return "<br>".join(keys)


def enum_columns(table: Table) -> set[str]:
    return {c.name for c in table.columns if isinstance(c.type, Enum)}


def business_checks(table: Table) -> list[CheckConstraint]:
    """Contraintes CHECK écrites à la main (les CHECK d'énumérations sont documentés avec elles)."""
    enums = enum_columns(table)
    checks = []
    for c in table.constraints:
        if not isinstance(c, CheckConstraint):
            continue
        text = str(c.sqltext)
        column = text.split(" IN (")[0].strip().rsplit(".", 1)[-1]
        if getattr(c, "_type_bound", False) or (" IN (" in text and column in enums):
            continue
        checks.append(c)
    return sorted(checks, key=lambda c: str(c.name))


def demo_row_counts() -> dict[str, int]:
    """Nombres de lignes d'une base en mémoire fraîchement remplie (déterministe)."""
    from app.seed import seed

    engine = create_engine("sqlite://")

    @event.listens_for(engine, "connect")
    def _fk(dbapi_connection, _record) -> None:
        dbapi_connection.execute("PRAGMA foreign_keys=ON")

    Base.metadata.create_all(engine)
    with Session(engine) as session:
        seed(session)
        counts = {
            t.name: session.scalar(select(func.count()).select_from(t))
            for t in Base.metadata.sorted_tables
        }
    engine.dispose()
    return counts


def collect_enums() -> dict[str, tuple[type[StrEnum], list[str]]]:
    enums: dict[str, tuple[type[StrEnum], list[str]]] = {}
    for table in Base.metadata.sorted_tables:
        for col in table.columns:
            if isinstance(col.type, Enum) and col.type.enum_class is not None:
                cls = col.type.enum_class
                enums.setdefault(cls.__name__, (cls, []))[1].append(f"{table.name}.{col.name}")
    return dict(sorted(enums.items()))


def mermaid_erd(tables: list[Table]) -> str:
    lines = ["```mermaid", "erDiagram"]
    seen = set()
    for table in tables:
        for fk in sorted(table.foreign_keys, key=lambda f: f.parent.name):
            parent = fk.column.table.name
            if parent == "sim_runs" and table.name != "sim_runs":
                continue  # sim_run_id, sur chaque table : décrit une fois
            optional = "o" if fk.parent.nullable else "|"
            edge = (parent, table.name, fk.parent.name)
            if edge in seen:
                continue
            seen.add(edge)
            lines.append(f'    {parent} |{optional}--o{{ {table.name} : "{fk.parent.name}"')
    lines.append("```")
    return "\n".join(lines)


def build(counts: dict[str, int] | None = None, generated_at: datetime | None = None) -> str:
    counts = counts if counts is not None else demo_row_counts()
    models = table_models()
    by_domain: dict[str, list[Table]] = defaultdict(list)
    for table in Base.metadata.sorted_tables:
        by_domain[table_domain(models[table.name])].append(table)
    for tables in by_domain.values():
        tables.sort(key=lambda t: t.name)

    all_tables = list(Base.metadata.sorted_tables)
    n_cols = sum(len(t.columns) for t in all_tables)
    n_fk = sum(len(t.foreign_keys) for t in all_tables)
    n_checks = sum(len(business_checks(t)) for t in all_tables)
    n_idx = sum(len(t.indexes) for t in all_tables)
    enums = collect_enums()

    out: list[str] = []
    w = out.append
    w("# Dictionnaire de données — Astro Assistant\n")
    w(
        "> Document généré par `python -m app.docs` à partir des modèles SQLAlchemy "
        "(`backend/app/models`). Ne pas modifier à la main.\n"
    )
    if generated_at:
        w(f"Généré le {generated_at:%d/%m/%Y à %H:%M}.\n")
    w("## Synthèse\n")
    w("| Élément | Nombre |\n|---|---:|")
    for label, value in (
        ("Tables", len(all_tables)),
        ("Colonnes", n_cols),
        ("Clés étrangères", n_fk),
        ("Contraintes CHECK métier", n_checks),
        ("Index secondaires", n_idx),
        ("Énumérations", len(enums)),
        ("Lignes après `python -m app.seed`", sum(counts.values())),
    ):
        w(f"| {label} | {value:,} |".replace(",", " "))
    w("")
    w("### Conventions\n")
    w(
        "- **Moteur** : SQLite 3 en mode WAL, sans serveur (exigence hors ligne du cahier "
        "des charges §8) ; le schéma reste portable vers PostgreSQL.\n"
        "- **Nommage** : tables au pluriel en `snake_case` anglais ; clé primaire `id` "
        "entière auto-incrémentée ; clé étrangère `<entité>_id`.\n"
        "- **Dates** : toutes les dates-heures sont en UTC ; les dates seules (`DATE`) sont "
        "des dates calendaires.\n"
        "- **Unités** : portées par le nom de colonne (`_msv`, `_ms`, `_kcal`, `_pfu`…) ou "
        "fixées par la métrique (`METRIC_UNITS`).\n"
        "- **Énumérations** : stockées en `VARCHAR(32)` avec une contrainte CHECK listant "
        "les valeurs autorisées.\n"
        "- **Simulation** : `sim_run_id` (nullable, ON DELETE CASCADE) est présent sur "
        "toutes les tables alimentées par le simulateur. Supprimer une exécution efface "
        "tout ce qu'elle a produit. Ces liens sont omis du diagramme pour le garder "
        "lisible.\n"
        "- **Légende des clés** : PK clé primaire, FK clé étrangère, UNIQUE valeur unique, "
        "IDX colonne indexée.\n"
    )

    w("## Tables par domaine fonctionnel\n")
    w("| Domaine | Table | Lignes (démo) | Rôle |\n|---|---|---:|---|")
    for key, label, _ in DOMAINS:
        for table in by_domain.get(key, []):
            first = describe(models[table.name]).split("\n")[0]
            link = f"[`{table.name}`](#{table.name})"
            w(f"| {label} | {link} | {counts.get(table.name, 0)} | {first} |")
    w("")

    w("## Modèle conceptuel\n")
    w(mermaid_erd(all_tables))
    w("")

    for key, label, intro in DOMAINS:
        tables = by_domain.get(key, [])
        if not tables:
            continue
        w(f"## {label}\n")
        w(f"{intro}\n")
        for table in tables:
            model = models[table.name]
            w(f'<a id="{table.name}"></a>\n')
            w(f"### `{table.name}`\n")
            w(f"{describe(model)}\n")
            w(
                f"Modèle `{model.__name__}` · {len(table.columns)} colonnes · "
                f"{counts.get(table.name, 0)} lignes dans la base de démonstration.\n"
            )
            w("| Colonne | Type | Null | Défaut | Clés | Description |")
            w("|---|---|:---:|---|---|---|")
            for col in table.columns:
                w(
                    f"| `{col.name}` | {column_type(col)} | {'oui' if col.nullable else 'non'} "
                    f"| {column_default(col)} | {column_keys(col, table)} | {col.comment or ''} |"
                )
            w("")
            fks = sorted(table.foreign_keys, key=lambda f: f.parent.name)
            if fks:
                w("**Clés étrangères**\n")
                for fk in fks:
                    w(
                        f"- `{fk.parent.name}` → `{fk.column.table.name}.{fk.column.name}` "
                        f"({ON_DELETE.get(fk.ondelete, fk.ondelete)})"
                    )
                w("")
            checks = business_checks(table)
            uniques = [
                u
                for u in table.constraints
                if isinstance(u, UniqueConstraint) and len(u.columns) > 1
            ]
            if checks or uniques:
                w("**Contraintes**\n")
                for u in uniques:
                    cols = ", ".join(f"`{c.name}`" for c in u.columns)
                    w(f"- UNIQUE ({cols})")
                for c in checks:
                    w(f"- CHECK `{c.name}` : `{c.sqltext}`")
                w("")
            composite = [i for i in table.indexes if len(i.columns) > 1]
            if composite:
                w("**Index composites**\n")
                for i in sorted(composite, key=lambda i: str(i.name)):
                    cols = ", ".join(f"`{c.name}`" for c in i.columns)
                    w(f"- `{i.name}` ({cols})")
                w("")

    w("## Énumérations\n")
    w("Valeurs autorisées par les contraintes CHECK des colonnes de type énuméré.\n")
    for name, (cls, used_by) in enums.items():
        w(f"### `{name}`\n")
        doc = pyinspect.cleandoc(cls.__doc__ or "")
        if doc and not doc.startswith("str(object"):
            w(f"{doc.splitlines()[0]}\n")
        w("Valeurs : " + ", ".join(f"`{m.value}`" for m in cls) + "\n")
        w("Utilisée par : " + ", ".join(f"`{u}`" for u in used_by) + "\n")

    w("## Déclencheurs\n")
    w(
        "- `audit_logs_no_update` et `audit_logs_no_delete` (SQLite) : toute tentative de "
        "`UPDATE` ou `DELETE` sur `audit_logs` est rejetée (`RAISE(ABORT)`). Le journal est "
        "en ajout seul (F14.1).\n"
    )
    return "\n".join(out).rstrip() + "\n"
