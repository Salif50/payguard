"""Gestionnaires de contexte encadrant une transaction atomique.

Principe (patron *mémento*) : à l'entrée du bloc ``with``, on capture l'état
de chaque participant ; si une exception s'échappe du bloc, on restaure
tous les états capturés, dans l'ordre inverse, puis on laisse l'exception se
propager. Le bloc est donc « tout ou rien ».

Le même mécanisme est écrit deux fois, comme le demande le sujet :

* :class:`TransactionAtomique` — classe avec ``__enter__`` / ``__exit__`` ;
* :func:`transaction_atomique` — générateur décoré par
  :func:`contextlib.contextmanager`.

Les participants n'ont qu'à respecter le protocole :class:`Restaurable`
(typage structurel) : ce module ne dépend donc pas des classes de comptes,
ce qui évite toute dépendance circulaire.
"""

from __future__ import annotations

import logging
from collections.abc import Iterator
from contextlib import contextmanager
from types import TracebackType
from typing import Any, Protocol, runtime_checkable

journal = logging.getLogger(__name__)


@runtime_checkable
class Restaurable(Protocol):
    """Objet dont l'état peut être capturé puis restauré."""

    def capturer_etat(self) -> Any:
        """Renvoie une copie de l'état mutable de l'objet."""
        ...

    def restaurer_etat(self, etat: Any) -> None:
        """Remet l'objet dans l'état ``etat``."""
        ...


def _verifier(participants: tuple[Restaurable, ...]) -> None:
    if not participants:
        raise ValueError("Une transaction atomique nécessite au moins un participant")
    for participant in participants:
        if not isinstance(participant, Restaurable):
            raise TypeError(f"{participant!r} n'implémente pas capturer_etat/restaurer_etat")


class TransactionAtomique:
    """Gestionnaire de contexte (version classe) garantissant le « tout ou rien ».

    Exemple ::

        with TransactionAtomique(emetteur, destinataire):
            emetteur.debiter(...)
            destinataire.crediter(...)   # si ceci échoue, le débit est annulé

    Après le bloc, :attr:`annulee` indique si une restauration a eu lieu.
    """

    def __init__(self, *participants: Restaurable) -> None:
        _verifier(participants)
        self._participants = participants
        self._etats: list[tuple[Restaurable, Any]] = []
        self.annulee = False

    def __enter__(self) -> TransactionAtomique:
        self._etats = [(p, p.capturer_etat()) for p in self._participants]
        self.annulee = False
        return self

    def __exit__(
        self,
        type_exception: type[BaseException] | None,
        exception: BaseException | None,
        trace: TracebackType | None,
    ) -> bool:
        if type_exception is not None:
            for participant, etat in reversed(self._etats):
                participant.restaurer_etat(etat)
            self.annulee = True
            journal.debug("Transaction annulée (%s) : état restauré", type_exception.__name__)
        self._etats = []
        return False  # ne jamais avaler l'exception


@contextmanager
def transaction_atomique(*participants: Restaurable) -> Iterator[None]:
    """Gestionnaire de contexte (version :mod:`contextlib`)
    équivalent à :class:`TransactionAtomique`."""
    _verifier(participants)
    etats = [(p, p.capturer_etat()) for p in participants]
    try:
        yield
    except BaseException as erreur:
        for participant, etat in reversed(etats):
            participant.restaurer_etat(etat)
        journal.debug("Transaction annulée (%s) : état restauré", type(erreur).__name__)
        raise
