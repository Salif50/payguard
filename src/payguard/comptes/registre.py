"""Collection de comptes parcourable, filtrable et triable."""

from __future__ import annotations

from collections.abc import Callable, Iterable, Iterator
from typing import Any

from payguard.comptes.base import Compte
from payguard.exceptions import CompteDejaExistant, CompteIntrouvable


class RegistreComptes:
    """Ensemble ordonné de comptes indexés par identifiant.

    Se comporte comme une collection Python native :

    * ``len(registre)``, ``for compte in registre``, ``"P000001" in registre``
      (ou ``compte in registre``), ``registre["P000001"]`` ;
    * ``sorted(registre)`` trie par identifiant (ordre naturel des comptes),
      ``sorted(registre, key=lambda c: c.solde)`` par solde ;
    * :meth:`filtrer` renvoie un nouveau registre (les comptes sont partagés,
      pas copiés).

    L'accès par identifiant est en O(1) grâce au dictionnaire interne, qui
    conserve aussi l'ordre d'insertion.
    """

    def __init__(self, comptes: Iterable[Compte] = ()) -> None:
        self._comptes: dict[str, Compte] = {}
        for compte in comptes:
            self.ajouter(compte)

    def ajouter(self, compte: Compte) -> None:
        """Ajoute un compte.

        Raises:
            TypeError: si l'objet n'est pas un :class:`Compte`.
            CompteDejaExistant: si l'identifiant est déjà présent.
        """
        if not isinstance(compte, Compte):
            raise TypeError(
                f"Seuls des comptes peuvent être ajoutés (reçu : {type(compte).__name__})"
            )
        if compte.id_compte in self._comptes:
            raise CompteDejaExistant(compte.id_compte)
        self._comptes[compte.id_compte] = compte

    def retirer(self, id_compte: str) -> Compte:
        """Retire et renvoie le compte ``id_compte``."""
        try:
            return self._comptes.pop(id_compte)
        except KeyError:
            raise CompteIntrouvable(id_compte) from None

    def obtenir(self, id_compte: str) -> Compte:
        """Renvoie le compte ``id_compte`` ou lève :class:`CompteIntrouvable`."""
        try:
            return self._comptes[id_compte]
        except KeyError:
            raise CompteIntrouvable(id_compte) from None

    def filtrer(self, predicat: Callable[[Compte], bool]) -> RegistreComptes:
        """Nouveau registre contenant les comptes pour lesquels ``predicat`` est vrai."""
        return RegistreComptes(c for c in self._comptes.values() if predicat(c))

    def par_type(self, classe: type[Compte]) -> RegistreComptes:
        """Comptes instances de ``classe`` (polymorphisme : sous-classes incluses)."""
        return self.filtrer(lambda c: isinstance(c, classe))

    def tries(
        self, cle: Callable[[Compte], Any] | None = None, decroissant: bool = False
    ) -> list[Compte]:
        """Liste triée des comptes (par identifiant si ``cle`` est ``None``)."""
        return sorted(self._comptes.values(), key=cle, reverse=decroissant)

    @property
    def solde_total(self) -> int:
        """Somme des soldes de tous les comptes du registre."""
        return sum(c.solde for c in self._comptes.values())

    def __len__(self) -> int:
        return len(self._comptes)

    def __iter__(self) -> Iterator[Compte]:
        return iter(self._comptes.values())

    def __contains__(self, element: object) -> bool:
        if isinstance(element, Compte):
            return (
                self._comptes.get(element.id_compte) is element
                or element.id_compte in self._comptes
            )
        return element in self._comptes

    def __getitem__(self, id_compte: str) -> Compte:
        return self.obtenir(id_compte)

    def __repr__(self) -> str:
        return f"RegistreComptes({len(self)} comptes, solde_total={self.solde_total})"
