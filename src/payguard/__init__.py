"""PayGuard — simulation d'un système de paiement mobile et détection de fraude.

Organisation du paquet :

* :mod:`payguard.generation` — phase 1 : génération de transactions synthétiques ;
* :mod:`payguard.comptes` — phase 2 : modèle objet (comptes, clients, plateforme) ;
* :mod:`payguard.outils` — phase 3 : décorateurs, gestionnaires de contexte, flux ;
* :mod:`payguard.donnees` — phase 4 : persistance SQLite, profils, analyse ;
* :mod:`payguard.detection` — phase 5 : moteur de règles et évaluation ;
* :mod:`payguard.cli` — phase 6 : interface en ligne de commande.

Les sous-paquets sont importés à la demande : ``import payguard`` reste
léger et n'importe ni pandas ni Matplotlib.
"""

from __future__ import annotations

import logging

__version__ = "1.0.0"

# Bonne pratique pour une bibliothèque : ne rien afficher tant que
# l'application n'a pas configuré la journalisation.
logging.getLogger(__name__).addHandler(logging.NullHandler())

__all__ = ["__version__"]
