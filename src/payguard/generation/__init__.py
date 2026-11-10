"""Phase 1 — génération de transactions synthétiques (bibliothèque standard).

Le module :mod:`payguard.generation.simulation` (phase 2) fait passer ces
mêmes opérations par la plateforme et ses règles métier ; il n'est pas
importé ici pour que la phase 1 reste indépendante du modèle objet.
"""

from payguard.generation.generateur import (
    ecrire_csv,
    generer_jeu_de_donnees,
    generer_transactions,
    valider_parametres,
)
from payguard.generation.scenarios import SCENARIOS

__all__ = [
    "SCENARIOS",
    "ecrire_csv",
    "generer_jeu_de_donnees",
    "generer_transactions",
    "valider_parametres",
]
