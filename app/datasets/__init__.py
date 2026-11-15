"""Jeux de données ouverts utilisés par Astro Assistant (cahier des charges §12).

- ``donki`` : événements de météo spatiale NASA DONKI (particules solaires, CME).
- ``goes`` : flux intégral de protons NOAA GOES (alertes de tempête radiative).
- ``msl_rad`` : débit de dose Curiosity RAD mesuré pendant le trajet vers Mars.
- ``catalog`` : grands jeux externes (physiologie, sommeil, stress) téléchargés à la demande.

Les petits extraits NASA sont versionnés dans ``data/nasa/`` pour une démo hors ligne ;
les grands jeux externes vont dans ``data/external/`` (ignoré par git).
Lancer ``python -m app.datasets --help`` pour la ligne de commande.
"""
