# AstroVitals — Backend (FastAPI)

Moteur Mentor IA : API REST + WebSocket, pipeline de données, scoring, règles cliniques, simulateur.

## Installation

```bash
python -m venv .venv
.venv/Scripts/activate        # Windows (bash) — `source .venv/bin/activate` sous Linux/macOS
pip install -e ".[dev]"
cp .env.example .env
```

## Lancement

```bash
uvicorn app.main:app --reload
```

- Swagger : http://localhost:8000/docs
- Santé : `GET /api/health`
- Temps réel : `ws://localhost:8000/ws`

## Tests et lint

```bash
pytest --cov=app
ruff check .
```

## Structure

```
app/
├── api/          # routes REST + WebSocket
├── core/         # config, base de données (SQLite WAL), sécurité, scheduler
├── models/       # SQLAlchemy
├── schemas/      # Pydantic
├── engine/       # features, scoring, ML, règles
├── protocols/    # fichiers YAML
└── sim/          # simulateur + scénarios
tests/
```
