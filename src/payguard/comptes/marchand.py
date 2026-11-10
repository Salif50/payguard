"""Compte d'un commerçant."""

from __future__ import annotations

import math
from datetime import datetime

from payguard.comptes.base import Compte
from payguard.comptes.client import Client
from payguard.comptes.transaction import TypeTransaction


class CompteMarchand(Compte):
    """Compte d'un commerçant : encaisse les paiements, plafonds élevés.

    * émet : retrait (récupérer la recette en espèces), transfert ;
    * reçoit : paiement marchand, dépôt, transfert ;
    * frais : 1 % sur les retraits, 0,5 % sur les transferts ;
    * plafonds : 20 000 000 GNF par retrait, 10 000 000 GNF par transfert,
      50 000 000 GNF par jour ; pas de plafond de solde.
    """

    TYPES_EMISSION = frozenset({TypeTransaction.RETRAIT, TypeTransaction.TRANSFERT})
    TYPES_RECEPTION = frozenset(
        {TypeTransaction.PAIEMENT_MARCHAND, TypeTransaction.DEPOT, TypeTransaction.TRANSFERT}
    )

    PLAFONDS_OPERATION = {
        TypeTransaction.RETRAIT: 20_000_000,
        TypeTransaction.TRANSFERT: 10_000_000,
    }
    PLAFOND_JOURNALIER = 50_000_000
    TAUX_FRAIS = {TypeTransaction.RETRAIT: 0.01, TypeTransaction.TRANSFERT: 0.005}

    def __init__(
        self,
        id_compte: str,
        titulaire: Client,
        solde_initial: int = 0,
        date_ouverture: datetime | None = None,
        categorie: str = "commerce",
    ) -> None:
        super().__init__(id_compte, titulaire, solde_initial, date_ouverture)
        self.categorie = categorie

    @property
    def type_compte(self) -> str:
        return "marchand"

    def plafond_operation(self, type_transaction: TypeTransaction) -> int:
        return self.PLAFONDS_OPERATION.get(type_transaction, 0)

    @property
    def plafond_journalier(self) -> int:
        return self.PLAFOND_JOURNALIER

    def calculer_frais(self, type_transaction: TypeTransaction, montant: int) -> int:
        return math.ceil(montant * self.TAUX_FRAIS.get(type_transaction, 0.0))
