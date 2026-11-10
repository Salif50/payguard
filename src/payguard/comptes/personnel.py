"""Compte d'un particulier."""

from __future__ import annotations

import math

from payguard.comptes.base import Compte
from payguard.comptes.transaction import TypeTransaction


class ComptePersonnel(Compte):
    """Compte d'un particulier : plafonds bas, frais sur transferts et retraits.

    * émet : retrait, transfert, paiement marchand ;
    * reçoit : dépôt (via un agent), transfert ;
    * frais : 1 % sur les transferts, 1,5 % sur les retraits, paiements gratuits ;
    * plafonds : 5 000 000 GNF par opération, 15 000 000 GNF par jour,
      solde plafonné à 50 000 000 GNF (compte de niveau « standard »).
    """

    TYPES_EMISSION = frozenset(
        {TypeTransaction.RETRAIT, TypeTransaction.TRANSFERT, TypeTransaction.PAIEMENT_MARCHAND}
    )
    TYPES_RECEPTION = frozenset({TypeTransaction.DEPOT, TypeTransaction.TRANSFERT})

    PLAFOND_OPERATION = 5_000_000
    PLAFOND_JOURNALIER = 15_000_000
    PLAFOND_SOLDE = 50_000_000
    TAUX_FRAIS = {
        TypeTransaction.TRANSFERT: 0.01,
        TypeTransaction.RETRAIT: 0.015,
        TypeTransaction.PAIEMENT_MARCHAND: 0.0,
    }

    @property
    def type_compte(self) -> str:
        return "personnel"

    def plafond_operation(self, type_transaction: TypeTransaction) -> int:
        return self.PLAFOND_OPERATION

    @property
    def plafond_journalier(self) -> int:
        return self.PLAFOND_JOURNALIER

    @property
    def plafond_solde(self) -> int | None:
        return self.PLAFOND_SOLDE

    def calculer_frais(self, type_transaction: TypeTransaction, montant: int) -> int:
        return math.ceil(montant * self.TAUX_FRAIS.get(type_transaction, 0.0))
