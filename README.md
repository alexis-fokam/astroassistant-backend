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

## Base de données

SQLite en mode WAL (`data/astrovitals.db`), créée au démarrage par `Base.metadata.create_all`.
Il n'y a pas encore de migrations : après un changement de modèle, supprimer `data/astrovitals.db*`.

| Domaine | Tables (`app/models/`) | Cahier des charges |
|---|---|---|
| Équipage | `crew_members` (profils locaux, PIN, rôle astronaute / CMO), `devices`, `baselines` | §7, §9, F2.1 |
| Mesures | `vital_readings`, `checkins` | F1, F3 |
| Radiation | `radiation_doses`, `space_weather_events` | F5 |
| Hygiène de vie | `exercise_sessions`, `sleep_sessions`, `pvt_results`, `intake_logs` | F6, F7, F8, F13 |
| Moteur IA | `feature_snapshots`, `risk_scores` (5 domaines + global) | F2 |
| Alertes | `alerts`, `emergency_events` | F2.7, F9.2, F12 |
| Protocoles | `protocols`, `protocol_requirements`, `protocol_runs` | F4, F11.2 |
| Médecine de bord | `consultation_notes`, `inventory_items`, `inventory_usages` | F9.3, F11 |
| Liaison sol | `sync_packets`, `ground_messages`, `contact_windows` | F10 |
| Traçabilité | `audit_logs` (chaîne SHA-256, UPDATE/DELETE bloqués par trigger) | F14.1 |
| Démo jury | `sim_scenarios`, `sim_runs` | F15 |

Toute donnée produite par le simulateur porte `sim_run_id` : supprimer un `SimRun` purge
en cascade tout ce qu'il a généré, sans toucher aux données réelles.

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
