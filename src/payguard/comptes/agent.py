"""Compte d'un agent (point de dépôt et de retrait d'espèces)."""

from __future__ import annotations

from payguard.comptes.base import Compte
from payguard.comptes.transaction import TypeTransaction


class CompteAgent(Compte):
    """Compte d'un agent de proximité qui échange espèces et monnaie électronique.

    Lors d'un dépôt, le client remet des espèces à l'agent, dont le compte
    est débité au profit de celui du client ; lors d'un retrait, c'est
    l'inverse. Le compte de l'agent est donc son « fonds de roulement ».

    * émet : dépôt (et transfert entre agents pour rééquilibrer la trésorerie) ;
    * reçoit : retrait, transfert ;
    * aucun frais (l'agent est rémunéré par commission, hors périmètre) ;
    * plafonds : 10 000 000 GNF par dépôt, 500 000 000 GNF par jour ;
    * contrôle spécifique : un agent ne peut pas se faire un dépôt à lui-même
      (vérifié par la plateforme, qui interdit émetteur = destinataire).
    """

    TYPES_EMISSION = frozenset({TypeTransaction.DEPOT, TypeTransaction.TRANSFERT})
    TYPES_RECEPTION = frozenset({TypeTransaction.RETRAIT, TypeTransaction.TRANSFERT})

    PLAFONDS_OPERATION = {
        TypeTransaction.DEPOT: 10_000_000,
        TypeTransaction.TRANSFERT: 100_000_000,
    }
    PLAFOND_JOURNALIER = 500_000_000

    @property
    def type_compte(self) -> str:
        return "agent"

    def plafond_operation(self, type_transaction: TypeTransaction) -> int:
        return self.PLAFONDS_OPERATION.get(type_transaction, 0)

    @property
    def plafond_journalier(self) -> int:
        return self.PLAFOND_JOURNALIER

    def calculer_frais(self, type_transaction: TypeTransaction, montant: int) -> int:
        return 0
