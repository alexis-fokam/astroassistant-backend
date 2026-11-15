# Fiche du moteur IA — Astro Assistant

*NASA Space Apps Challenge 2026 · version `risk-engine 1.1.0`*

Cette fiche répond à quatre questions du jury : quelles données le moteur utilise, comment il décide, pourquoi ses seuils sont ceux-là, et ce qu'il vaut. Le code est dans `backend/app/engine/`. Les seuils et les règles sont dans deux fichiers lisibles, `config.yaml` et `rules.yaml`.

> Astro Assistant est un **prototype d'aide à la décision**. Ce n'est pas un dispositif médical certifié. Le moteur ne prescrit aucun médicament : il signale, explique et propose un protocole, et c'est le médecin de bord qui décide.

## 1. Ce que fait le moteur

Toutes les 5 secondes, pour chaque astronaute qui a reçu de nouvelles mesures, le moteur enchaîne cinq étapes :

| Étape | Ce qui est fait | Fichier |
|---|---|---|
| 1. Nettoyage | Il écarte les valeurs hors plage physiologique et les mesures de qualité inférieure à 0,5. | `features.py`, `config.yaml` |
| 2. Références individuelles | Pour chaque astronaute, il calcule la médiane, la MAD, la moyenne et l'écart-type sur 14 jours. Les 3 derniers jours sont exclus, pour qu'une dérive en cours ne devienne pas « normale ». La référence est recalculée une fois par jour. | `baselines.py` |
| 3. Indicateurs | Il calcule : la valeur actuelle (5 min) ; les moyennes sur 1 h et 24 h ; les z-scores robustes ; le ratio VFC/référence et sa pente ; la dette de sommeil ; les séances manquées et l'assiduité ; la projection de perte osseuse ; le PVT ; le check-in ; le débit et la dose de carrière ; le flux de protons GOES. | `features.py` |
| 4. Détection | 13 règles cliniques et un Isolation Forest par astronaute, entraîné sur sa propre référence. | `rules.yaml`, `anomaly.py` |
| 5. Scores et alertes | Il produit un score de 0 à 100 par domaine avec ses 3 facteurs explicatifs, puis le score global et le statut. Il crée les alertes en évitant les doublons, en recommandant un protocole et en inscrivant chaque alerte au journal d'audit. | `scoring.py`, `pipeline.py`, `services/alerts.py` |

**Comment une alerte est confirmée (§6.3).** Une règle **critique** se déclenche immédiatement. Une règle d'**avertissement** doit tenir sur **deux mesures consécutives**, ce qui écarte les pics isolés. Une règle plus spécifique masque les règles générales qu'elle recouvre : par exemple, `CARDIO-CRIT-01` masque `HR-02`.

**Comment les scores sont calculés.**
- Pour chaque domaine, le score vaut `100 × min(1, Σ poids × sévérité)`, où la sévérité de chaque indicateur est ramenée entre 0 et 1.
- Une règle confirmée impose un plancher : 45 pour un avertissement, 75 pour une alerte critique.
- Le score global vaut `0,5 × pire domaine + 0,5 × moyenne pondérée des domaines`. Les poids sont : cardio 0,30, comportemental 0,25, radiations 0,20, musculo-squelettique 0,15, immunitaire 0,10.
- Le statut est le plus grave des deux : le niveau du score global, ou la pire règle déclenchée. Les seuils sont 0-39 nominal, 40-69 avertissement, 70-100 critique.

## 2. Les règles et l'origine de leurs seuils

| Code | Domaine | Niveau | Condition | Protocole | Source du seuil |
|---|---|---|---|---|---|
| `CARDIO-CRIT-01` | Cardio | Critique | FC > 120 bpm **et** SpO₂ < 94 % | EMRG-01 | Seuils cliniques usuels (tachycardie, hypoxémie) |
| `SPO2-CRIT-01` | Cardio | Critique | SpO₂ ≤ 90 % | EMRG-01 | Hypoxémie sévère (seuil clinique standard) |
| `HR-02` | Cardio | Avertissement | z-score robuste de la FC sur 1 h ≥ 2,5 | — | Statistique : environ 1 % de faux positifs sous une loi normale |
| `ANOMALY-01` | Cardio | Avertissement | Score Isolation Forest ≥ 0,85 | — | Modèle entraîné sur la référence individuelle (contamination 2 %) |
| `SANS-01` | Neuro-oculaire | Avertissement | Vision modifiée ≥ 2/3 **et** céphalées ≥ 2/3, 2 jours | PRT-SANS-01 | NASA HRP, risque SANS (syndrome neuro-oculaire du vol spatial) |
| `HRV-01` | Comportemental | Avertissement | VFC < 80 % de la référence **et** (stress ≥ 7/10 **ou** 3 nuits < 6 h) | PRT-STRESS-01 | Cahier des charges F4.2 ; à confirmer sur WESAD (§4) |
| `HRV-TREND-01` | Comportemental | Avertissement | Pente de la VFC ≤ −0,15 ms/h (−3,6 ms/jour) **et** VFC < 90 % | — | Détection précoce d'une baisse de la VFC |
| `PVT-01` | Comportemental | Avertissement | ≥ 3 inattentions **et** temps de réaction ≥ 115 % de l'habituel | — | PVT de 3 min, inattention = réponse > 500 ms (Basner et al.) |
| `EX-MISSED-01` | Musculo-squelettique | Avertissement | ≥ 2 séances de résistance manquées d'affilée | PRT-EX-03 | Cahier des charges F6 |
| `RAD-SPE-01` | Radiations | Critique | Débit ≥ 0,104 mSv/h (2,5 mSv/jour) | PRT-RAD-02 | **Données réelles** : Curiosity RAD, fond de 1,67 mSv/jour (notebook `analyse_radiations_nasa`) |
| `GOES-S1-01` | Radiations | Avertissement | Flux de protons ≥ 10 MeV au-delà de 10 pfu | PRT-RAD-02 | **Échelle NOAA S1**, alerte précoce |
| `RAD-CAREER-01` | Radiations | Avertissement | Dose de carrière ≥ 80 % de la limite | — | Limite de carrière NASA : 600 mSv |
| `TEMP-01` | Immunitaire | Avertissement | Température ≥ 38,0 °C | — | Seuil clinique de la fièvre |

**Projection de la perte osseuse.** Le moteur calcule `1,25 %/mois × (1 − 0,8 × assiduité aux séances de résistance)`, puis l'extrapole à la durée de la mission. La perte de densité minérale de la hanche sans contre-mesure vient de LeBlanc et al. (2000) et du risque « ostéoporose précoce » du NASA HRP.

## 3. Les données utilisées

| Données | Nature | Usage dans le moteur |
|---|---|---|
| Curiosity RAD, NASA PDS (5 117 mesures, 2011-2012) | Réelles | Bruit de fond et seuil de tempête (`RAD-SPE-01`) ; profil de dose de l'historique de démo |
| NASA DONKI (502 événements) et NOAA GOES | Réelles | Validation des pics de dose ; alerte précoce (`GOES-S1-01`) |
| BIDMC, PhysioNet (53 patients) | Réelles | Distributions de SpO₂, FC et FR (§4) |
| Sleep-EDF Expanded, PhysioNet | Réelles | Sommeil d'adultes sains : seuil des nuits courtes (§4) |
| WESAD, université de Siegen (15 personnes) | Réelles | Sensibilité et fausses alertes de la règle VFC/stress (§4) |
| Historique de démo (14 jours, 4 astronautes) | **Fictives** | Tests d'acceptation de bout en bout uniquement |

Aucune donnée physiologique individuelle d'astronaute n'est publique. L'équipage de démonstration est donc fictif, et les seuils sont justifiés par des données terrestres réelles ou par la littérature.

## 4. Calibration et performances mesurées

| Mesure | Résultat | Comment le reproduire |
|---|---|---|
| Scénarios de la démo (J+142) | Les 4 situations sont retrouvées sans intervention : AV-01 en avertissement (`EX-MISSED-01`), AV-02 en avertissement (`HRV-01`), AV-03 en critique (`CARDIO-CRIT-01`, anomalie 0,77), AV-04 en avertissement (`SANS-01`) | `pytest tests/test_engine.py` |
| Pics isolés et artefacts | Une FC isolée à 140 bpm ne déclenche pas d'avertissement ; une FC à 400 bpm et une SpO₂ de mauvaise qualité sont écartées | `pytest tests/test_engine.py` |
| Tempête solaire | `RAD-SPE-01` se déclenche immédiatement ; `GOES-S1-01` se déclenche après deux relevés GOES consécutifs | `pytest tests/test_engine.py` |
| Temps de calcul | ≈ 85 ms par astronaute, modèles déjà entraînés (cible < 200 ms) | `POST /api/v1/engine/run` |
| Couverture des tests du moteur | 93 % (cible ≥ 70 %) | `pytest --cov=app.engine` |
| BIDMC, Sleep-EDF | *À exécuter* | `python -m app.datasets fetch bidmc`, `python -m app.datasets fetch sleep-edf`, puis `python -m app.engine.calibration bidmc sleep` |
| WESAD : sensibilité et taux de fausses alertes de `HRV-01` | *À exécuter, après téléchargement manuel de WESAD* | `python -m app.engine.calibration wesad` |

Les résultats chiffrés de la calibration sont écrits dans `docs/calibration.json`.

## 5. Limites connues

- **Seuils encore à confirmer.** Tant que l'évaluation sur WESAD n'a pas tourné, le seuil de 80 % de la VFC reste une valeur de la littérature.
- **Populations différentes.** Les données terrestres (étudiants pour WESAD, patients de soins intensifs pour BIDMC, adultes sains pour Sleep-EDF) ne reproduisent pas la physiologie en microgravité. Elles servent à **calibrer des ordres de grandeur**, pas à valider le moteur pour le vol.
- **Mesures de radiation partielles.** Curiosity RAD n'a été mesuré qu'un jour sur trois, et le blindage du rover n'est pas celui d'un habitat.
- **Isolation Forest.** Il faut au moins 72 h de données propres par astronaute avant que le modèle puisse fonctionner.
- **Projection osseuse.** C'est un modèle linéaire simple, pas un modèle physiologique.

## 6. Garde-fous

- **Explicabilité (F2.7).** Chaque alerte indique sa règle, ses 3 facteurs principaux, son score d'anomalie et son nombre de confirmations (`GET /api/v1/alerts/{id}/explanation`).
- **Supervision humaine.** Seul le médecin de bord peut acquitter une alerte ou clôturer une urgence.
- **Traçabilité.** Chaque alerte et chaque exécution du moteur sont inscrites dans le journal d'audit chaîné par SHA-256.
- **Reproductibilité.** Les graines aléatoires sont fixes. Les modèles sont sauvegardés avec joblib dans `data/models/`. Chaque score porte la version du moteur qui l'a calculé.
