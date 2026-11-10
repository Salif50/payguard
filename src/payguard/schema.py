"""Format du fichier d'échange (annexe A du sujet).

Ce module ne dépend que de la bibliothèque standard : il est partagé par le
générateur (phase 1), le modèle objet (phase 2) et la lecture en flux
(phase 3), sans créer de dépendance entre ces couches.
"""

from __future__ import annotations

#: Colonnes du CSV, dans l'ordre imposé par l'annexe A.
COLONNES: tuple[str, ...] = (
    "id_transaction",
    "horodatage",
    "id_emetteur",
    "id_destinataire",
    "type",
    "montant",
    "zone",
    "appareil_id",
    "est_fraude",
)

#: Colonne d'étiquette, absente du jeu de test remis à la soutenance.
COLONNE_ETIQUETTE: str = "est_fraude"

#: Colonnes indispensables à la détection (l'étiquette est facultative).
COLONNES_OBLIGATOIRES: tuple[str, ...] = tuple(c for c in COLONNES if c != COLONNE_ETIQUETTE)

#: Valeurs autorisées de la colonne ``type``.
TYPES_OPERATIONS: tuple[str, ...] = ("depot", "retrait", "transfert", "paiement_marchand")
