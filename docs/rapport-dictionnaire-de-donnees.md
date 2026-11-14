# Rapport sur le dictionnaire de données — Astro Assistant

*NASA Space Apps Challenge 2026 · défi « Create Health Monitoring Software for Astronauts on Space Missions »*

Ce rapport présente la base de données restructurée d'Astro Assistant. Il explique les choix de modélisation, l'origine des données et la façon dont leur qualité est contrôlée. Le détail colonne par colonne se trouve dans le [dictionnaire de données](dictionnaire-de-donnees.md), généré à partir du code.

---

## 1. Synthèse

| Indicateur | Valeur |
|---|---:|
| Tables | **31** (27 avant restructuration) |
| Colonnes, toutes décrites | **327** (100 % commentées) |
| Domaines fonctionnels | 13 |
| Clés étrangères | 60 |
| Contraintes CHECK métier | 57 (plus 30 CHECK générées pour les énumérations) |
| Index secondaires | 54 |
| Énumérations | 22 |
| Lignes dans la base de démonstration | ≈ 20 000 (détail au §6) |
| Tests automatisés | 30, tous verts |

Trois points résument la base :

- **Elle couvre tout le cahier des charges.** Chaque exigence F1 à F15 a au moins une table. La référence (F…, §…) est indiquée dans la description de chaque table.
- **Les données spatiales sont réelles.** Elles viennent de la NASA (Curiosity RAD) et de la NOAA (GOES). Une table dédiée trace l'origine de chaque valeur.
- **La documentation ne peut pas dériver.** Le dictionnaire est produit par `python -m app.docs` à partir des modèles, et un test échoue si une colonne n'est pas décrite.

## 2. Ce qui a changé

| Changement | Pourquoi |
|---|---|
| Nouvelle table `missions` (destination, latence, durée du jour local) ; `crew_members.mission_id` et `contact_windows.mission_id` | L'écran de configuration A-03 choisit un profil de mission. La latence (720 s vers Mars) et le cycle jour/nuit (1 477 min pour un sol martien) ne sont plus codés en dur. |
| Nouvelle table `dataset_sources` | Provenance : agence, licence, URL, date de récupération et nombre de lignes de chaque jeu ouvert (critère « utilisation des données des agences spatiales »). |
| Nouvelles tables `cruise_dose_samples` et `proton_flux_readings` | Mesures réelles : débit de dose de Curiosity RAD en transit vers Mars, et flux de protons GOES. Elles servent de référence au simulateur de radiations et à l'alerte précoce (F5.4). |
| `space_weather_events.source_id` | Distingue un événement réel (DONKI, NOAA) d'un événement simulé. |
| `radiation_doses.neutron_fraction` | Part des neutrons dans la dose, mise en avant par l'Agence spatiale canadienne (ressource du défi). |
| `checkins` : `dizziness`, `skin_issue`, `crew_relations` | Couvre les risques HRP cités par le défi : troubles vestibulaires, dermatologie et cohésion d'équipe. |
| Énumération `DataSource.DATASET` et `MissionDestination` | Une mesure importée d'un jeu ouvert se distingue d'une mesure de capteur. Le profil de mission est contrôlé par une liste fermée. |
| Commentaire `comment=` sur les 327 colonnes, docstring en français sur les 31 modèles | Ils alimentent automatiquement le dictionnaire. Les commentaires sont aussi écrits dans le schéma SQL quand le moteur les supporte (PostgreSQL). |
| `ContactWindow.mission`, hachage d'audit normalisé en UTC | Corrige deux défauts : la fenêtre de contact n'était rattachée à aucune mission, et la chaîne d'audit ne se vérifiait plus après relecture depuis SQLite, qui renvoie des dates sans fuseau. |

## 3. Organisation logique

```
Mission ─┬─ Équipage et capteurs ─┬─ Télémétrie et check-in ──┐
         │                        ├─ Bien-être                ├─► Moteur IA ─► Alertes ─► Protocoles
         │                        └─ Radiations ◄─ Données ouvertes (NASA/NOAA)          │
         └─ Liaison sol (fenêtres, paquets, consignes)        Médecine de bord ◄─────────┘
Transversal : Audit (toutes les actions) · Simulation (sim_run_id sur 16 tables)
```

| Domaine | Tables | Rôle |
|---|---:|---|
| Mission | 1 | Profil de mission et paramètres de liaison |
| Équipage et capteurs | 3 | Profils locaux (PIN haché), capteurs, baselines individuelles |
| Télémétrie et check-in | 2 | Constantes (format long) et auto-déclaration quotidienne |
| Bien-être | 4 | Exercice, sommeil, test de vigilance (PVT), nutrition |
| Radiations | 2 | Événements de météo spatiale, dosimétrie individuelle |
| Données ouvertes | 3 | Provenance et mesures réelles NASA/NOAA |
| Moteur IA | 2 | Indicateurs calculés et scores de risque explicables |
| Alertes et urgences | 2 | Alertes cliniques, mode urgence |
| Protocoles | 3 | Bibliothèque versionnée, matériel requis, exécutions |
| Médecine de bord | 3 | Journal médical, pharmacie, registre des usages |
| Liaison sol | 3 | File d'export signée, consignes du sol, fenêtres de contact |
| Audit | 1 | Journal non modifiable chaîné |
| Simulation | 2 | Scénarios S1 à S6 et leurs exécutions |

## 4. Choix de modélisation

1. **Constantes au format long.** `vital_readings` stocke une ligne par mesure : membre, métrique, valeur, instant. Ajouter un capteur ne demande aucune migration. L'unité est fixée par la métrique (`METRIC_UNITS`), et l'index (`crew_member_id`, `metric`, `recorded_at`) sert les courbes du tableau de bord.
2. **Énumérations en `VARCHAR(32)` avec CHECK.** C'est portable (SQLite aujourd'hui, PostgreSQL demain) et aussi strict qu'un type ENUM natif. Les 22 listes de valeurs sont dans le dictionnaire.
3. **JSON réservé au contenu semi-structuré.** Il ne sert que pour les facteurs explicatifs d'un score (F2.7), les étapes d'un protocole, les indicateurs calculés et les détails d'audit. Ce sont des données lues d'un bloc et jamais filtrées en SQL.
4. **Instantanés plutôt que valeurs courantes.** `risk_scores`, `baselines` et `radiation_doses` historisent chaque calcul. Le tableau de bord lit la dernière ligne, et le médecin peut retracer l'évolution d'un risque.
5. **Règles de suppression explicites.** Chacune des 60 clés étrangères a son comportement documenté :
   - **CASCADE** (36) pour les données qui appartiennent à un membre ou à une simulation ;
   - **SET NULL** (19) pour les liens facultatifs, par exemple l'alerte à l'origine d'une consultation ;
   - **RESTRICT** (5) quand une suppression effacerait une trace. Un protocole déjà exécuté, un article de pharmacie déjà utilisé ou un auteur du journal d'audit ne peuvent pas être supprimés.
6. **Simulation isolée.** 16 tables portent `sim_run_id` avec ON DELETE CASCADE. Supprimer une exécution du simulateur efface tout ce qu'elle a produit, sans toucher aux données de mission.
7. **Cohérence garantie par la base.** Les 57 contraintes métier :
   - encadrent les plages : symptômes de 0 à 3, ressentis de 0 à 10, score de 0 à 100, SpO₂, efficacité de 0 à 1 ;
   - imposent la chronologie : une fin est postérieure au début ;
   - imposent les dépendances entre champs : une alerte acquittée a une date d'acquittement, une séance réalisée a une durée, une prise d'eau a un volume ;
   - imposent le cumul de dose : cumul carrière ≥ cumul mission.

## 5. Origine des données

| Source | Table | Nature | Licence |
|---|---|---|---|
| NASA PDS — Curiosity RAD, croisière vers Mars 2011-2012 (`MSL-M-RAD-3-RDR-V1.0`) | `cruise_dose_samples` | **Réelle.** Débits de dose B/E en µGy/h et équivalent de dose avec Q ≈ 3,8 (Zeitlin et al., *Science* 2013). Un jour sur trois est retenu. | Domaine public (US Gov) |
| NOAA SWPC — GOES, flux intégral de protons sur 7 jours | `proton_flux_readings` | **Réelle.** Bandes ≥ 10 MeV (seuil de tempête S1) et ≥ 100 MeV. | Domaine public |
| NASA DONKI (SEP, CME) ou rapports NOAA | `space_weather_events` | **Réelle.** Éruptions X8.2 (sept. 2017) et X5.8 (mai 2024), et événement à protons du 10/09/2017 (≈ 1 490 pfu), rejoué par le scénario S3. | Domaine public |
| WESAD, Sleep-EDF, BIDSleep, Monash PVT, NASA OSDR Inspiration4 | `dataset_sources`, sans import | Référencés pour entraîner et valider le moteur. Téléchargés à la demande dans `data/external/` (non versionné). | Selon chaque jeu |
| Générateur `app/sim/history.py` | Toutes les tables opérationnelles | **Fictive**, déterministe (graine 142) | — |

> Aucune donnée physiologique réelle d'astronaute n'est publique au niveau individuel. L'équipage et sa télémétrie sont donc fictifs, mais calibrés sur les ordres de grandeur publiés par le NASA Human Research Program. L'environnement radiatif, lui, est mesuré : la dose de fond de chaque membre suit le profil réel de Curiosity, corrigé par un facteur de blindage propre à chacun.

## 6. Jeu de données fictif

Le jeu couvre les 14 derniers jours de la mission **Artemis-M** (transit vers Mars, départ le 24/05/2026, latence 12 min) et s'arrête à **J+142 · 14:05 UTC**. C'est l'horloge affichée par le frontend, donc l'application et la base racontent la même histoire.

| Membre | Situation à J+142 | Données qui la portent |
|---|---|---|
| AV-01 Nadia Okafor (commandante) | 3 séances ARED manquées : risque musculo-squelettique, **WARNING 41** | `exercise_sessions` (statut `missed`), alerte acquittée, protocole PRT-EX-03 en cours |
| AV-02 Léo Martin (ingénieur de vol) | VFC tombée à 65 % de sa baseline, sommeil < 6 h trois nuits de suite : **WARNING 54** | courbe `hrv_rmssd`, `sleep_sessions`, PVT dégradé, check-ins stress 7/10, consigne du sol |
| AV-03 Sara Lindqvist (spécialiste) | Tachycardie à 128 bpm et SpO₂ à 92 % depuis 4 min : **CRITICAL 81** | mesures toutes les 5 min, alerte détectée par Isolation Forest, urgence active, EMRG-01, oxygène sorti de la pharmacie |
| AV-04 Kenji Arai (médecin de bord) | Vision floue et céphalées depuis 2 jours : suspicion de SANS, **WARNING 47** | check-ins, alerte « Neuro-oculaire », PRT-SANS-01, paracétamol |
| Tout l'équipage, il y a 2 jours | Rejeu de l'événement à protons de 2017 : mise à l'abri B2 | `space_weather_events`, pic de dose, 4 alertes critiques résolues, 4 PRT-RAD-02 terminés |

Volumes principaux :

| Table | Lignes |
|---|---:|
| `vital_readings` | ≈ 9 000 (1 point par heure par métrique, toutes les 5 min sur les 2 dernières heures) |
| `proton_flux_readings` | ≈ 4 000 (réelles) |
| `cruise_dose_samples` | ≈ 2 000 à 6 000 (réelles, selon la couverture du téléchargement RAD) |
| `risk_scores` / `feature_snapshots` | 1 440 / 240 (toutes les 6 h, 6 domaines par membre) |
| `radiation_doses` | ≈ 1 400 (horaires, cumuls croissants) |
| `intake_logs`, `exercise_sessions`, `sleep_sessions`, `checkins`, `pvt_results` | 520, 120, 56, 56, 60 |
| `audit_logs` | ≈ 80 entrées chaînées |

La valeur exacte de chaque table figure dans le dictionnaire. Elle est recalculée à chaque génération.

## 7. Qualité et intégrité

- **Intégrité référentielle** : `PRAGMA foreign_keys=ON` à chaque connexion. Le seed complet passe avec les clés étrangères actives.
- **Contraintes de domaine** : 57 CHECK métier et 30 CHECK d'énumération. Une valeur hors plage est rejetée par la base, pas seulement par l'API.
- **Journal d'audit** : il est en ajout seul, et des déclencheurs SQLite rejettent `UPDATE` et `DELETE`. Chaque entrée contient le SHA-256 de la précédente. Un test recharge la base et revérifie toute la chaîne.
- **Paquets vers le sol** : le contenu est vraiment compressé en gzip et son empreinte SHA-256 est stockée. Un test décompresse chaque paquet et recalcule son empreinte.
- **Reproductibilité** : deux générations avec la même graine produisent des bases identiques, ce qu'un test vérifie.
- **Documentation** : des tests garantissent que chaque colonne a une description, que chaque table a une docstring et un domaine, et que le dictionnaire affiche les 31 tables.

## 8. Confidentialité et sécurité

- Les données de santé sont des données sensibles. La base reste **locale à l'appareil** (fonctionnement hors ligne). Seuls des paquets de synthèse, signés, partent vers le sol.
- Les PIN ne sont **jamais stockés en clair** : seule leur empreinte PBKDF2-SHA256 salée est conservée (`crew_members.pin_hash`).
- Contrôle d'accès (§7) : `access_role` sépare l'astronaute, qui ne voit que ses propres données, du médecin de bord. Seul le médecin de bord peut enregistrer un usage de la pharmacie (`inventory_usages.recorded_by_id`).
- Un profil n'est jamais supprimé, seulement désactivé (`is_active`), pour que la piste d'audit reste complète.
- Toutes les personnes de la base de démonstration sont fictives. Les seules mesures réelles concernent l'environnement spatial, pas des individus.

## 9. Limites et suites

| Limite | Piste |
|---|---|
| Pas de migrations : un changement de modèle impose de recréer la base | Ajouter Alembic avant toute donnée de production |
| DONKI est limité par la clé `DEMO_KEY` ; les événements de référence NOAA prennent le relais | Créer une clé gratuite sur api.nasa.gov (`AV_NASA_API_KEY`) puis lancer `python -m app.datasets fetch donki` |
| Les jeux physiologiques terrestres (WESAD, Sleep-EDF…) sont catalogués mais pas importés | Les importer dans `data/external/` pour entraîner et valider le moteur IA |
| SQLite n'est pas chiffré au repos | SQLCipher, ou chiffrement du volume de l'appareil |
| Les commentaires de colonnes ne sont pas écrits dans le fichier SQLite, qui ne les supporte pas | Ils sont repris dans le dictionnaire, et PostgreSQL les conserverait |

## 10. Régénérer les livrables

```bash
cd backend
python -m app.datasets fetch all --every 3   # données ouvertes (RAD, GOES, DONKI)
python -m app.seed --reset                    # base de démonstration
python -m app.docs                            # docs/dictionnaire-de-donnees.md
pytest                                        # 30 tests
```
