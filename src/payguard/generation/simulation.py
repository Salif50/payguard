"""Phase 2 — le générateur alimente la plateforme : les données passent par les règles métier.

Les opérations produites par :func:`~payguard.generation.generateur.generer_transactions`
ne sont plus écrites telles quelles : elles sont *exécutées* par une
:class:`~payguard.comptes.plateforme.Plateforme` peuplée d'objets
:class:`~payguard.comptes.base.Compte`. Seules les opérations acceptées
(solde suffisant, plafonds respectés, types autorisés...) figurent dans
l'historique final ; les rejets sont comptés par motif.
"""

from __future__ import annotations

import csv
import logging
from collections import Counter
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Any

from payguard.comptes.agent import CompteAgent
from payguard.comptes.base import Compte
from payguard.comptes.client import Client
from payguard.comptes.marchand import CompteMarchand
from payguard.comptes.personnel import ComptePersonnel
from payguard.comptes.plateforme import Plateforme
from payguard.comptes.transaction import Transaction
from payguard.exceptions import PayGuardError
from payguard.generation import generateur as gen
from payguard.outils.decorateurs import chronometre
from payguard.schema import COLONNES

journal = logging.getLogger(__name__)

_CLASSES: dict[str, type[Compte]] = {
    "personnel": ComptePersonnel,
    "marchand": CompteMarchand,
    "agent": CompteAgent,
}


@dataclass
class ResultatSimulation:
    """Résultat d'une simulation : plateforme finale, transactions acceptées, rejets."""

    plateforme: Plateforme
    transactions: list[Transaction]
    rejets: Counter[str] = field(default_factory=Counter)
    rejets_fraude: int = 0
    scenarios: dict[str, str] = field(default_factory=dict)

    @property
    def nb_fraudes(self) -> int:
        """Nombre de transactions frauduleuses acceptées."""
        return sum(1 for t in self.transactions if t.est_fraude)

    def resume(self) -> dict[str, Any]:
        """Résumé chiffré, prêt à afficher."""
        nb = len(self.transactions)
        return {
            "nb_transactions_acceptees": nb,
            "nb_rejets": sum(self.rejets.values()),
            "rejets_par_motif": dict(self.rejets),
            "rejets_frauduleux": self.rejets_fraude,
            "nb_fraudes": self.nb_fraudes,
            "taux_fraude": self.nb_fraudes / nb if nb else 0.0,
            "revenus_plateforme": self.plateforme.revenus,
            "nb_comptes": len(self.plateforme),
        }


def construire_compte(description: dict[str, Any]) -> Compte:
    """Instancie le bon type de compte à partir d'une description du générateur."""
    titulaire = Client(description["id_client"], description["nom"], description["telephone"])
    classe = _CLASSES[description["type"]]
    return classe(
        description["id"],
        titulaire,
        solde_initial=int(description["solde_initial"]),
        date_ouverture=description["date_creation"],
    )


def construire_plateforme(descriptions: list[dict[str, Any]]) -> Plateforme:
    """Crée une plateforme et y ouvre un compte par description."""
    plateforme = Plateforme()
    for description in descriptions:
        plateforme.ouvrir_compte(construire_compte(description))
    return plateforme


@chronometre
def simuler(
    nb_comptes: int = gen.NB_COMPTES_DEFAUT,
    nb_operations: int = gen.NB_OPERATIONS_DEFAUT,
    debut: date = gen.DEBUT_DEFAUT,
    fin: date = gen.FIN_DEFAUT,
    taux_fraude: float = gen.TAUX_FRAUDE_DEFAUT,
    graine: int = gen.GRAINE_DEFAUT,
) -> ResultatSimulation:
    """Génère comptes et opérations puis les exécute sur la plateforme.

    Mêmes paramètres que :func:`~payguard.generation.generateur.generer_transactions`.
    """
    descriptions, operations = gen.generer_transactions(
        nb_comptes, nb_operations, debut, fin, taux_fraude, graine
    )
    plateforme = construire_plateforme(descriptions)
    acceptees: list[Transaction] = []
    scenarios: dict[str, str] = {}
    rejets_fraude = 0
    for operation in operations:
        try:
            transaction = plateforme.executer(
                operation["type"],
                operation["id_emetteur"],
                operation["id_destinataire"],
                operation["montant"],
                horodatage=operation["horodatage"],
                zone=operation["zone"],
                appareil_id=operation["appareil_id"],
                id_transaction=operation["id_transaction"],
                est_fraude=bool(operation["est_fraude"]),
            )
        except PayGuardError as erreur:
            rejets_fraude += operation["est_fraude"]
            journal.debug("Opération %s rejetée : %s", operation["id_transaction"], erreur)
            continue
        acceptees.append(transaction)
        if operation["est_fraude"]:
            scenarios[transaction.id_transaction] = operation["scenario"]
    resultat = ResultatSimulation(
        plateforme, acceptees, Counter(plateforme.rejets), rejets_fraude, scenarios
    )
    journal.info("Simulation : %s", resultat.resume())
    return resultat


def ecrire_transactions(transactions: list[Transaction], chemin: str | Path) -> int:
    """Écrit des :class:`Transaction` au format de l'annexe A."""
    chemin = Path(chemin)
    chemin.parent.mkdir(parents=True, exist_ok=True)
    with chemin.open("w", newline="", encoding="utf-8") as fichier:
        ecrivain = csv.DictWriter(fichier, fieldnames=COLONNES)
        ecrivain.writeheader()
        for transaction in transactions:
            ecrivain.writerow(transaction.vers_ligne())
    return len(transactions)


def ecrire_scenarios(scenarios: dict[str, str], chemin: str | Path) -> int:
    """Écrit le fichier annexe ``id_transaction,scenario`` des fraudes acceptées."""
    chemin = Path(chemin)
    chemin.parent.mkdir(parents=True, exist_ok=True)
    with chemin.open("w", newline="", encoding="utf-8") as fichier:
        ecrivain = csv.writer(fichier)
        ecrivain.writerow(["id_transaction", "scenario"])
        ecrivain.writerows(sorted(scenarios.items()))
    return len(scenarios)
