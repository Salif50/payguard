"""Configuration centralisée du module :mod:`logging`.

Les modules de la bibliothèque se contentent de ``logging.getLogger(__name__)``
et n'ajoutent jamais de gestionnaire : c'est l'application (la CLI, le
notebook) qui décide où et à quel niveau les messages sont écrits, en
appelant :func:`configurer_journalisation` une seule fois.
"""

from __future__ import annotations

import logging
from pathlib import Path

FORMAT_JOURNAL = "%(asctime)s | %(levelname)-8s | %(name)s | %(message)s"
FORMAT_DATE = "%Y-%m-%d %H:%M:%S"
_MARQUEUR = "_payguard_gestionnaire"


def configurer_journalisation(
    niveau: int | str = logging.INFO,
    fichier: str | Path | None = None,
    niveau_console: int | str | None = logging.WARNING,
    exclus_console: tuple[str, ...] = (),
) -> logging.Logger:
    """Configure le journal racine du paquet ``payguard``.

    Args:
        niveau: niveau minimal des messages écrits dans le fichier de journal.
        fichier: chemin du fichier de journal ; ``None`` pour ne pas en écrire.
        niveau_console: niveau minimal affiché sur la sortie d'erreur ;
            ``None`` pour ne rien afficher en console.
        exclus_console: journaux (par nom) à ne pas répéter en console, par
            exemple celui de la CLI qui affiche déjà ses erreurs à l'utilisateur.

    Returns:
        Le journal ``payguard`` configuré.

    L'appel est idempotent : les gestionnaires posés par un appel précédent
    sont retirés avant d'en poser de nouveaux (utile dans les tests et les
    notebooks, qui peuvent appeler la fonction plusieurs fois).
    """
    journal = logging.getLogger("payguard")
    for gestionnaire in list(journal.handlers):
        if getattr(gestionnaire, _MARQUEUR, False):
            journal.removeHandler(gestionnaire)
            gestionnaire.close()

    formateur = logging.Formatter(FORMAT_JOURNAL, datefmt=FORMAT_DATE)
    niveaux = [logging.getLevelName(niveau) if isinstance(niveau, str) else niveau]

    if fichier is not None:
        chemin = Path(fichier)
        chemin.parent.mkdir(parents=True, exist_ok=True)
        gestionnaire_fichier = logging.FileHandler(chemin, encoding="utf-8")
        gestionnaire_fichier.setLevel(niveau)
        gestionnaire_fichier.setFormatter(formateur)
        setattr(gestionnaire_fichier, _MARQUEUR, True)
        journal.addHandler(gestionnaire_fichier)

    if niveau_console is not None:
        gestionnaire_console = logging.StreamHandler()
        gestionnaire_console.setLevel(niveau_console)
        gestionnaire_console.setFormatter(formateur)
        if exclus_console:
            gestionnaire_console.addFilter(
                lambda enregistrement: enregistrement.name not in exclus_console
            )
        setattr(gestionnaire_console, _MARQUEUR, True)
        journal.addHandler(gestionnaire_console)
        niveaux.append(
            logging.getLevelName(niveau_console)
            if isinstance(niveau_console, str)
            else niveau_console
        )

    journal.setLevel(min(niveaux))
    journal.propagate = False
    return journal


def reinitialiser_journalisation() -> None:
    """Retire les gestionnaires posés par :func:`configurer_journalisation`
    et rétablit la propagation."""
    journal = logging.getLogger("payguard")
    for gestionnaire in list(journal.handlers):
        if getattr(gestionnaire, _MARQUEUR, False):
            journal.removeHandler(gestionnaire)
            gestionnaire.close()
    journal.setLevel(logging.NOTSET)
    journal.propagate = True
