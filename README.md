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

31 tables réparties en 13 domaines, chaque colonne décrite en français. Le détail est dans
[`docs/dictionnaire-de-donnees.md`](docs/dictionnaire-de-donnees.md), généré à partir des modèles,
et les choix de conception dans [`docs/rapport-dictionnaire-de-donnees.md`](docs/rapport-dictionnaire-de-donnees.md).

| Domaine | Tables (`app/models/`) | Cahier des charges |
|---|---|---|
| Mission | `missions` (destination, latence, durée du jour local) | A-03 |
| Équipage | `crew_members` (profils locaux, PIN, rôle astronaute / CMO), `devices`, `baselines` | §7, §9, F2.1 |
| Mesures | `vital_readings`, `checkins` | F1, F3 |
| Radiation | `radiation_doses`, `space_weather_events` | F5 |
| Données ouvertes | `dataset_sources`, `cruise_dose_samples` (Curiosity RAD), `proton_flux_readings` (GOES) | §12 |
| Hygiène de vie | `exercise_sessions`, `sleep_sessions`, `pvt_results`, `intake_logs` | F6, F7, F8, F13 |
| Moteur IA | `feature_snapshots`, `risk_scores` (5 domaines + global) | F2 |
| Alertes | `alerts`, `emergency_events` | F2.7, F9.2, F12 |
| Protocoles | `protocols`, `protocol_requirements`, `protocol_runs` | F4, F11.2 |
| Médecine de bord | `consultation_notes`, `inventory_items`, `inventory_usages` | F9.3, F11 |
| Liaison sol | `sync_packets`, `ground_messages`, `contact_windows` | F10 |
| Traçabilité | `audit_logs` (chaîne SHA-256, UPDATE/DELETE bloqués par trigger) | F14.1 |
| Démo jury | `sim_scenarios`, `sim_runs` | F15 |

### Données de démo

```bash
python -m app.datasets fetch all --every 3   # données ouvertes NASA/NOAA dans data/nasa/
python -m app.seed --reset                    # recrée les tables puis remplit
python -m app.seed --reset --no-history       # référentiel et données ouvertes seulement
python -m app.docs                            # régénère le dictionnaire de données
```

Le seed charge :

- la mission Artemis-M et 4 membres d'équipage fictifs (AV-04 est le médecin de bord), avec leurs capteurs et baselines ;
- la pharmacie, les 5 protocoles YAML et les scénarios S1 à S6 ;
- les mesures réelles NASA/NOAA présentes dans `data/nasa/` ;
- un historique fictif et déterministe de 14 jours (`app/sim/history.py`) qui s'arrête à J+142 · 14:05 UTC, l'horloge du frontend, et reprend l'histoire des maquettes : sommeil d'AV-02, SANS d'AV-04, urgence d'AV-03, tempête solaire rejouée.

Les PIN de démo sont dans `DEMO_PINS` (`app/seed.py`).

Toute donnée produite par le simulateur porte `sim_run_id` : supprimer un `SimRun` purge
en cascade tout ce qu'il a généré, sans toucher aux données réelles.

## Structure

```
app/
├── api/          # routes REST + WebSocket
├── core/         # config, base de données (SQLite WAL), sécurité, scheduler
├── datasets/     # téléchargement et import des données ouvertes NASA/NOAA
├── docs/         # génération du dictionnaire de données
├── models/       # SQLAlchemy
├── schemas/      # Pydantic
├── engine/       # features, scoring, ML, règles
├── protocols/    # fichiers YAML
└── sim/          # simulateur, scénarios, historique de démo
docs/             # dictionnaire de données et rapport
tests/
```
