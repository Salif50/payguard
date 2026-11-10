"""Décorateurs transverses : mesure du temps, journalisation des appels, nouvelles tentatives.

Les trois décorateurs utilisent :func:`functools.wraps`, qui recopie le nom,
la docstring, le module, les annotations et ``__wrapped__`` de la fonction
d'origine : ``help()``, ``inspect.signature()`` et pytest continuent donc de
voir la vraie signature.
"""

from __future__ import annotations

import functools
import logging
import time
from collections.abc import Callable
from typing import ParamSpec, TypeVar

P = ParamSpec("P")
R = TypeVar("R")

journal = logging.getLogger(__name__)


def chronometre(fonction: Callable[P, R]) -> Callable[P, R]:
    """Mesure la durée d'exécution de la fonction et la journalise (niveau INFO).

    La dernière durée mesurée (en secondes) est aussi exposée dans
    l'attribut ``derniere_duree`` de la fonction décorée, ce qui permet de
    l'exploiter dans un benchmark ou un test.
    """

    @functools.wraps(fonction)
    def enveloppe(*args: P.args, **kwargs: P.kwargs) -> R:
        debut = time.perf_counter()
        try:
            return fonction(*args, **kwargs)
        finally:
            duree = time.perf_counter() - debut
            enveloppe.derniere_duree = duree  # type: ignore[attr-defined]
            logging.getLogger(fonction.__module__).info(
                "%s exécutée en %.3f s", fonction.__qualname__, duree
            )

    enveloppe.derniere_duree = None  # type: ignore[attr-defined]
    return enveloppe


def journaliser(fonction: Callable[P, R]) -> Callable[P, R]:
    """Journalise l'appel, le résultat et les exceptions de la fonction (niveau DEBUG).

    Les exceptions sont journalisées puis **relancées** : le décorateur
    observe, il ne modifie jamais le comportement. Le formatage des
    arguments n'est fait que si le niveau DEBUG est actif, pour ne rien
    coûter en production.
    """
    journal_fonction = logging.getLogger(fonction.__module__)

    @functools.wraps(fonction)
    def enveloppe(*args: P.args, **kwargs: P.kwargs) -> R:
        actif = journal_fonction.isEnabledFor(logging.DEBUG)
        if actif:
            arguments = [repr(a) for a in args] + [f"{k}={v!r}" for k, v in kwargs.items()]
            journal_fonction.debug("Appel %s(%s)", fonction.__qualname__, ", ".join(arguments))
        try:
            resultat = fonction(*args, **kwargs)
        except Exception as erreur:
            journal_fonction.debug(
                "%s a levé %s : %s", fonction.__qualname__, type(erreur).__name__, erreur
            )
            raise
        if actif:
            journal_fonction.debug("%s a renvoyé %r", fonction.__qualname__, resultat)
        return resultat

    return enveloppe


def reessayer(
    n: int = 3,
    delai: float = 0.1,
    exceptions: tuple[type[BaseException], ...] = (Exception,),
    facteur: float = 1.0,
) -> Callable[[Callable[P, R]], Callable[P, R]]:
    """Décorateur paramétré : réessaie la fonction en cas d'échec transitoire.

    Args:
        n: nombre total de tentatives (au moins 1).
        delai: attente en secondes avant la deuxième tentative.
        exceptions: exceptions considérées comme transitoires ; les autres
            sont relancées immédiatement.
        facteur: multiplicateur du délai entre deux tentatives
            (``2.0`` donne un recul exponentiel).

    Après ``n`` échecs, la dernière exception est relancée.

    Raises:
        ValueError: si ``n < 1`` ou ``delai < 0`` (à la décoration).
    """
    if not isinstance(n, int) or n < 1:
        raise ValueError(f"n doit être un entier >= 1 (reçu : {n!r})")
    if delai < 0 or facteur < 1:
        raise ValueError("delai doit être >= 0 et facteur >= 1")

    def decorateur(fonction: Callable[P, R]) -> Callable[P, R]:
        @functools.wraps(fonction)
        def enveloppe(*args: P.args, **kwargs: P.kwargs) -> R:
            attente = delai
            for tentative in range(1, n + 1):
                try:
                    return fonction(*args, **kwargs)
                except exceptions as erreur:
                    if tentative == n:
                        journal.error(
                            "%s : échec définitif après %d tentatives (%s)",
                            fonction.__qualname__,
                            n,
                            erreur,
                        )
                        raise
                    journal.warning(
                        "%s : tentative %d/%d échouée (%s), nouvel essai dans %.2f s",
                        fonction.__qualname__,
                        tentative,
                        n,
                        erreur,
                        attente,
                    )
                    time.sleep(attente)
                    attente *= facteur
            raise AssertionError("inatteignable")  # pragma: no cover

        return enveloppe

    return decorateur
