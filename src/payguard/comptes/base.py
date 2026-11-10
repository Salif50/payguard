"""Classe abstraite :class:`Compte`, socle commun des trois types de comptes."""

from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import date, datetime
from functools import total_ordering
from typing import ClassVar

from payguard.comptes.client import Client
from payguard.comptes.transaction import TypeTransaction
from payguard.exceptions import (
    CompteGele,
    OperationNonAutorisee,
    ParametreInvalide,
    PlafondDepasse,
    SoldeInsuffisant,
)

#: État capturé d'un compte : (solde, jour du cumul, cumul du jour, gelé).
EtatCompte = tuple[int, "date | None", int, bool]


@total_ordering
class Compte(ABC):
    """Compte de monnaie électronique (montants entiers en GNF).

    Responsabilités :

    * encapsuler le solde (lecture seule depuis l'extérieur : seules les
      méthodes :meth:`debiter` et :meth:`crediter` le modifient) ;
    * appliquer les contrôles communs dans un ordre fixe (patron *méthode
      patron*) : gel, type d'opération autorisé, plafond par opération,
      plafond journalier, solde suffisant frais compris ;
    * déléguer aux classes filles ce qui varie : plafonds, frais, types
      d'opérations autorisés (méthodes polymorphes).

    Égalité et hachage reposent sur l'identifiant : deux objets décrivant le
    même compte sont égaux. L'ordre naturel est celui des identifiants, ce
    qui rend ``sorted(comptes)`` déterministe ; pour trier par solde on
    passe une clé (``sorted(comptes, key=lambda c: c.solde)``).
    """

    #: Types d'opérations que ce compte peut *émettre* (être débité).
    TYPES_EMISSION: ClassVar[frozenset[TypeTransaction]] = frozenset()
    #: Types d'opérations que ce compte peut *recevoir* (être crédité).
    TYPES_RECEPTION: ClassVar[frozenset[TypeTransaction]] = frozenset()

    def __init__(
        self,
        id_compte: str,
        titulaire: Client,
        solde_initial: int = 0,
        date_ouverture: datetime | None = None,
    ) -> None:
        if not isinstance(id_compte, str) or not id_compte.strip():
            raise ParametreInvalide("L'identifiant du compte doit être une chaîne non vide")
        if not isinstance(titulaire, Client):
            raise ParametreInvalide("Le titulaire doit être une instance de Client")
        if (
            not isinstance(solde_initial, int)
            or isinstance(solde_initial, bool)
            or solde_initial < 0
        ):
            raise ParametreInvalide(
                f"Le solde initial doit être un entier positif ou nul (reçu : {solde_initial!r})"
            )
        self._id_compte = id_compte.strip()
        self._titulaire = titulaire
        self._solde = solde_initial
        self._date_ouverture = date_ouverture
        self._gele = False
        self._jour_cumul: date | None = None
        self._cumul_jour = 0

    # ------------------------------------------------------------------
    # Accès en lecture
    # ------------------------------------------------------------------

    @property
    def id_compte(self) -> str:
        """Identifiant unique du compte."""
        return self._id_compte

    @property
    def titulaire(self) -> Client:
        """Client titulaire du compte (composition)."""
        return self._titulaire

    @property
    def solde(self) -> int:
        """Solde courant en GNF (lecture seule)."""
        return self._solde

    @property
    def date_ouverture(self) -> datetime | None:
        """Date d'ouverture du compte, si connue."""
        return self._date_ouverture

    @property
    def est_gele(self) -> bool:
        """Vrai si le compte est gelé."""
        return self._gele

    # ------------------------------------------------------------------
    # Comportements polymorphes (à fournir par les classes filles)
    # ------------------------------------------------------------------

    @property
    @abstractmethod
    def type_compte(self) -> str:
        """Libellé du type de compte (``personnel``, ``marchand``, ``agent``)."""

    @abstractmethod
    def plafond_operation(self, type_transaction: TypeTransaction) -> int:
        """Montant maximal d'une seule opération de ce type émise par le compte."""

    @property
    @abstractmethod
    def plafond_journalier(self) -> int:
        """Cumul maximal des débits sur une journée calendaire."""

    @abstractmethod
    def calculer_frais(self, type_transaction: TypeTransaction, montant: int) -> int:
        """Frais (GNF, entiers) facturés à l'émetteur pour cette opération."""

    @property
    def plafond_solde(self) -> int | None:
        """Solde maximal autorisé ; ``None`` signifie « pas de plafond »."""
        return None

    def peut_emettre(self, type_transaction: TypeTransaction) -> bool:
        """Indique si le compte peut être débité pour ce type d'opération."""
        return type_transaction in self.TYPES_EMISSION

    def peut_recevoir(self, type_transaction: TypeTransaction) -> bool:
        """Indique si le compte peut être crédité pour ce type d'opération."""
        return type_transaction in self.TYPES_RECEPTION

    # ------------------------------------------------------------------
    # Opérations
    # ------------------------------------------------------------------

    @staticmethod
    def _verifier_montant(montant: int) -> None:
        if not isinstance(montant, int) or isinstance(montant, bool) or montant <= 0:
            raise ParametreInvalide(
                f"Le montant doit être un entier strictement positif (reçu : {montant!r})"
            )

    def _cumul_du_jour(self, jour: date) -> int:
        return self._cumul_jour if self._jour_cumul == jour else 0

    def verifier_debit(
        self, montant: int, type_transaction: TypeTransaction, instant: datetime
    ) -> int:
        """Contrôle un débit sans le réaliser et renvoie les frais qui seraient prélevés.

        Raises:
            CompteGele, OperationNonAutorisee, PlafondDepasse, SoldeInsuffisant.
        """
        self._verifier_montant(montant)
        if self._gele:
            raise CompteGele(self._id_compte)
        if not self.peut_emettre(type_transaction):
            raise OperationNonAutorisee(
                f"Un compte {self.type_compte} ne peut pas "
                f"émettre l'opération {type_transaction.value}"
            )
        plafond = self.plafond_operation(type_transaction)
        if montant > plafond:
            raise PlafondDepasse(self._id_compte, "par opération", plafond, montant)
        cumul = self._cumul_du_jour(instant.date()) + montant
        if cumul > self.plafond_journalier:
            raise PlafondDepasse(self._id_compte, "journalier", self.plafond_journalier, cumul)
        frais = self.calculer_frais(type_transaction, montant)
        if montant + frais > self._solde:
            raise SoldeInsuffisant(self._id_compte, self._solde, montant + frais)
        return frais

    def debiter(self, montant: int, type_transaction: TypeTransaction, instant: datetime) -> int:
        """Débite le compte du montant et des frais, après tous les contrôles.

        Returns:
            Les frais prélevés (à reverser à la plateforme).
        """
        frais = self.verifier_debit(montant, type_transaction, instant)
        jour = instant.date()
        self._cumul_jour = self._cumul_du_jour(jour) + montant
        self._jour_cumul = jour
        self._solde -= montant + frais
        return frais

    def crediter(self, montant: int, type_transaction: TypeTransaction) -> None:
        """Crédite le compte après contrôle du gel, du type et du plafond de solde."""
        self._verifier_montant(montant)
        if self._gele:
            raise CompteGele(self._id_compte)
        if not self.peut_recevoir(type_transaction):
            raise OperationNonAutorisee(
                f"Un compte {self.type_compte} ne peut pas "
                f"recevoir l'opération {type_transaction.value}"
            )
        plafond = self.plafond_solde
        if plafond is not None and self._solde + montant > plafond:
            raise PlafondDepasse(self._id_compte, "de solde", plafond, self._solde + montant)
        self._solde += montant

    def geler(self) -> None:
        """Gèle le compte : plus aucun débit ni crédit possible."""
        self._gele = True

    def degeler(self) -> None:
        """Lève le gel du compte."""
        self._gele = False

    # ------------------------------------------------------------------
    # Mémento : capture et restauration de l'état (atomicité)
    # ------------------------------------------------------------------

    def capturer_etat(self) -> EtatCompte:
        """Capture l'état mutable du compte (utilisé par les transactions atomiques)."""
        return (self._solde, self._jour_cumul, self._cumul_jour, self._gele)

    def restaurer_etat(self, etat: EtatCompte) -> None:
        """Restaure un état précédemment capturé par :meth:`capturer_etat`."""
        self._solde, self._jour_cumul, self._cumul_jour, self._gele = etat

    # ------------------------------------------------------------------
    # Méthodes spéciales
    # ------------------------------------------------------------------

    def __repr__(self) -> str:
        gel = ", gele=True" if self._gele else ""
        return (
            f"{type(self).__name__}(id_compte={self._id_compte!r}, "
            f"titulaire={self._titulaire.nom!r}, solde={self._solde}{gel})"
        )

    def __eq__(self, autre: object) -> bool:
        if not isinstance(autre, Compte):
            return NotImplemented
        return self._id_compte == autre._id_compte

    def __hash__(self) -> int:
        return hash(self._id_compte)

    def __lt__(self, autre: object) -> bool:
        if not isinstance(autre, Compte):
            return NotImplemented
        return self._id_compte < autre._id_compte
