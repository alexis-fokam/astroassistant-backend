# Astro Assistant — Backend (FastAPI)

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
- Santé : `GET /api/v1/health`
- Temps réel : `ws://localhost:8000/ws/telemetry` (mesures, alertes, urgences)

## API REST (`/api/v1`, cahier des charges §10)

Authentification : `POST /api/v1/auth/login` avec `{"code": "AV-02", "pin": "2222"}`
renvoie un jeton à passer dans `Authorization: Bearer <jeton>`. Un astronaute ne voit que ses
propres données ; le médecin de bord (AV-04) voit tout l'équipage et est seul à pouvoir
acquitter une alerte, enregistrer un usage de pharmacie, clôturer une urgence ou lire l'audit.

| Domaine | Routes |
|---|---|
| Profil | `POST /auth/login`, `GET /auth/me`, `GET /mission` |
| Équipage | `GET /crew`, `GET /crew/{code}/status` |
| Mesures | `POST /vitals`, `GET /vitals/{code}?type=&from=&to=`, `GET /radiation/{code}` |
| Auto-déclaration | `POST /checkins`, `POST /exercises`, `POST /pvt` |
| Alertes | `GET /alerts?status=active`, `GET` / `PATCH /alerts/{id}` |
| Protocoles | `GET /protocols`, `GET /protocols/{code}`, `POST /protocols/{code}/runs`, `PATCH /protocols/runs/{id}` |
| Pharmacie | `GET /inventory`, `POST /inventory` |
| Urgence | `POST` / `GET /emergency`, `POST /emergency/{id}/steps`, `POST /emergency/{id}/close` |
| Rapports | `GET /reports/{code}?period=week` |
| Liaison sol | `POST /sync/export`, `GET /sync/packets`, `POST /sync/import`, `GET /sync/messages`, `GET /sync/windows` |
| Simulation | `GET /sim/scenarios`, `POST /sim/scenario`, `POST /sim/speed`, `GET /sim/runs`, `POST /sim/runs/{id}/stop` |
| Traçabilité | `GET /audit`, `GET /audit/verify`, `GET /datasets` |

L'horloge de mission suit la dernière télémétrie reçue : avec la base de démo, l'API répond
à J+142 · 14:05, comme le frontend.

## Moteur IA (`app/engine/`, cahier des charges §6)

Toutes les 5 s (`AV_PIPELINE_INTERVAL_SECONDS`), le pipeline reprend chaque membre dont de
nouvelles mesures sont arrivées :

1. **Nettoyage** : valeurs hors plage physiologique ou de qualité < 0,5 écartées (`config.yaml`).
2. **Indicateurs** : valeur actuelle (5 min), moyennes 1 h et 24 h, z-scores robustes par
   rapport à la baseline individuelle, ratio VFC/baseline, dette de sommeil, séances manquées,
   PVT, check-in, débit et dose de carrière (`features.py`).
3. **Règles cliniques** en YAML (`rules.yaml`), avec les mêmes codes que les protocoles
   (`HRV-01`, `SANS-01`, `EX-MISSED-01`, `RAD-SPE-01`…). Une règle WARNING doit tenir sur deux
   mesures consécutives ; une règle CRITICAL déclenche immédiatement.
4. **Isolation Forest** par astronaute, entraîné sur sa propre baseline (`anomaly.py`).
5. **Scores 0-100** par domaine avec les 3 facteurs explicatifs, score global et statut
   (`scoring.py`) ; alertes créées sans doublon par `app/services/alerts.py`.

Les seuils de radiation viennent du notebook `analyse_radiations_nasa.ipynb`. Sur la base de
démo, le moteur retrouve seul l'histoire de J+142 : AV-01 en WARNING (séances manquées), AV-02
en WARNING (VFC basse), AV-03 en CRITICAL (tachycardie et désaturation), AV-04 en WARNING
(suspicion de SANS). Routes : `GET /api/v1/engine/status`, `POST /api/v1/engine/run` (CMO),
`GET /api/v1/alerts/{id}/explanation`, `GET /api/v1/crew/{code}/domains/{domain}`.
Désactiver la tâche de fond : `AV_PIPELINE_ENABLED=false`.

Fiche du moteur pour le jury (données, règles, origine des seuils, performances, limites) :
[`docs/fiche-moteur-ia.md`](docs/fiche-moteur-ia.md). Calibration sur données réelles :

```bash
python -m app.datasets fetch bidmc        # PhysioNet BIDMC, ~1 Mo
python -m app.datasets fetch sleep-edf    # PhysioNet Sleep-EDF (hypnogrammes), ~1 Mo
python -m app.engine.calibration all      # écrit docs/calibration.json
```

WESAD (~2,5 Go) se télécharge à la main depuis
https://www.eti.uni-siegen.de/ubicomp/home/datasets/icmi18/ dans `data/external/wesad/`.

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
