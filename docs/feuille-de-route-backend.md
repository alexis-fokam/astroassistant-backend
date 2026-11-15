# Feuille de route backend — API pour le frontend

**Responsable :** @gazonsn-del
**Branche de départ :** `main` (après fusion de `feat/database-schema`)

Ce document liste tout ce qu'il reste à faire sur le backend pour que le frontend (Nuxt) consomme l'API directement, avant l'intégration du moteur IA.

## Démarrer

```bash
python -m app.seed --reset
uvicorn app.main:app --reload
```

- Documentation interactive : http://localhost:8000/docs
- Tests : `pytest` (56 tests, tous verts)
- Comptes de démo : AV-01 = 1111, AV-02 = 2222, AV-03 = 3333, AV-04 = 4444 (médecin de bord)

## 1. Règles communes de l'API

- **Préfixe** : `/api/v1`.
- **Format JSON** : en **camelCase**, avec `alias_generator=to_camel` et `populate_by_name=True` dans les schémas Pydantic, pour que le front n'ait rien à convertir.
- **Dates** : ISO 8601, UTC.
- **Niveaux** : `nominal`, `warning`, `critical`, `info`, toujours en minuscules.
- **Domaines de risque** : `cardio`, `radiation`, `musculoskeletal`, `behavioral`, `immune`.
- **Erreurs** : format `{"detail": "message en français"}`. Codes HTTP :
  - 401 : non connecté ;
  - 403 : interdit ;
  - 404 : introuvable ;
  - 409 : conflit ;
  - 422 : données invalides.
- **Authentification** : en-tête `Authorization: Bearer <token>`, avec le jeton obtenu au login.
- **Rôles** : un astronaute ne voit que ses propres données (403 sinon) ; le médecin de bord (AV-04) voit tout l'équipage.
- **Audit** : toute écriture est enregistrée dans le journal d'audit (`app/services/audit.py`).
- **Temps réel** : le WebSocket `/ws/telemetry` envoie des messages `{type, …}`, avec `type` parmi `vitals`, `score`, `alert`, `emergency` et `sim`.

## 2. Endpoints existants à tester

| Domaine | Endpoints |
|---|---|
| Connexion | `POST /auth/login`, `GET /auth/me` |
| Mission et équipage | `GET /mission`, `GET /crew`, `GET /crew/{code}/status` |
| Mesures | `POST /vitals`, `GET /vitals/{code}?type=&from=&to=`, `GET /radiation/{code}` |
| Auto-déclaration | `POST /checkins`, `POST /exercises`, `POST /pvt` |
| Alertes | `GET /alerts?status=active`, `GET /alerts/{id}`, `PATCH /alerts/{id}` |
| Protocoles | `GET /protocols`, `GET /protocols/{code}`, `POST /protocols/{code}/runs`, `PATCH /protocols/runs/{id}` |
| Pharmacie | `GET /inventory`, `POST /inventory` |
| Urgence | `POST /emergency`, `GET /emergency`, `POST /emergency/{id}/steps`, `POST /emergency/{id}/close` |
| Rapports | `GET /reports/{code}?period=week` |
| Liaison sol | `POST /sync/export`, `GET /sync/packets`, `POST /sync/import`, `GET /sync/messages`, `POST /sync/messages/{id}/read`, `GET /sync/windows` |
| Simulation | `GET /sim/scenarios`, `POST /sim/scenario`, `POST /sim/speed`, `GET /sim/runs`, `POST /sim/runs/{id}/stop` |
| Traçabilité | `GET /audit`, `GET /audit/verify`, `GET /datasets` |

## 3. Endpoints à créer pour les écrans du frontend

| Écran | Endpoint | Contenu attendu |
|---|---|---|
| Connexion | ~~`GET /profiles`~~ ✅ fait (PR #6) | code, prénom, nom, rôle, `isCmo` |
| Connexion | `POST /auth/logout` | invalide la session |
| En-tête | `GET /mission` (à compléter) | ajouter `missionTime`, `clock` (« J+142 · 14:05 ») et le compte à rebours jusqu'au prochain contact |
| Tableau de bord astronaute | ~~`GET /crew/{code}/vitals/latest`~~ ✅ fait (PR #6) | pour chaque constante : dernière valeur, unité, niveau, tendance en %, bande normale (baseline ± 2σ), 36 derniers points |
| Détail d'une alerte | ~~`GET /alerts/{id}/explanation`~~ ✅ fait | facteurs (libellé, valeur, contribution), règle déclenchée, score d'anomalie, nombre de confirmations |
| Systèmes | ~~`GET /crew/{code}/domains/{domain}`~~ ✅ fait | historique du score du domaine et facteurs |
| Historiques | `GET /checkins/{code}`, `GET /sleep/{code}`, `GET /exercises/{code}`, `GET /pvt/{code}` | listes paginées, les plus récentes d'abord |
| Protocoles | `GET /protocols/runs?crew=&status=` | exécutions en cours et terminées |
| Médecin de bord | `GET /consultations/{code}`, `POST /consultations/{code}` | journal médical (F9.3) |
| Pharmacie | `GET /inventory/usages` | registre des usages |
| Météo spatiale | `GET /space-weather/events` | événements DONKI et simulés |
| Simulation | `GET /sim/runs/{id}/events` | journal du moteur affiché pendant la démo |

## 4. Fonctionnalités à coder

1. ✅ **Moteur IA et pipeline planifié** : fait (`app/engine/`, voir le README). La tâche tourne toutes les 5 s et ne recalcule un membre que si de nouvelles mesures sont arrivées. Routes : `GET /engine/status` et `POST /engine/run`.
2. ✅ **Service `create_alert`** : fait (`app/services/alerts.py`). Il enregistre l'alerte, l'inscrit dans l'audit et évite les doublons ; le pipeline la diffuse sur le WebSocket.
3. **Simulateur** (`app/sim/`) : il injecte la télémétrie des scénarios S1 à S6, avec la vitesse choisie et le `sim_run_id`, quand on appelle `/sim/scenario` et `/sim/speed`.
4. **Validation des mesures** : rejet des valeurs physiologiquement impossibles dans `POST /vitals` et marquage des artefacts.
5. **Sécurité de la connexion** : blocage d'un profil pendant 5 min après 3 PIN faux, et déconnexion.
6. **Déploiement** : `Dockerfile` et `docker-compose.yml` (`docker compose up`, §7 du cahier des charges), plus les migrations Alembic.

## 5. Tests attendus

Chaque endpoint doit avoir ses tests :

- le cas normal ;
- l'accès refusé (401 et 403) ;
- les données invalides (422) ;
- les conflits (409).

Les tests existants doivent rester verts, et la couverture doit dépasser 70 %.

## Priorités

1. ✅ `GET /profiles` et `GET /crew/{code}/vitals/latest` (PR #6). Reste l'horloge « J+142 · 14:05 » dans `GET /mission`.
2. Les historiques (`/checkins`, `/sleep`, `/exercises`, `/pvt`) et les consultations.
3. Le simulateur : le moteur IA est prêt et traite déjà les mesures d'une simulation en cours (`sim_run_id`).
4. Le reste des endpoints, la sécurité, Docker et Alembic.
