"""Lecture en flux du fichier de transactions et fenêtre glissante par compte.

* :func:`lire_transactions` est un **générateur** : il produit une
  :class:`~payguard.comptes.transaction.Transaction` à la fois, sans jamais
  charger le fichier entier en mémoire.
* :func:`lire_par_blocs` regroupe ce flux en listes de taille fixe (insertion
  SQLite par lots, traitement par paquets).
* :class:`FenetreGlissanteParCompte` est un **itérateur** écrit à la main
  (``__iter__`` / ``__next__``) qui associe à chaque transaction les
  dernières transactions du même compte.
"""

from __future__ import annotations

import csv
import logging
from collections import deque
from collections.abc import Callable, Iterable, Iterator
from datetime import timedelta
from itertools import islice
from pathlib import Path

from payguard.comptes.transaction import Transaction
from payguard.exceptions import DonneesInvalides, ParametreInvalide
from payguard.schema import COLONNES_OBLIGATOIRES

journal = logging.getLogger(__name__)


class RapportLecture:
    """Compteurs renseignés pendant la lecture d'un fichier (lignes lues, rejetées, étiquette)."""

    def __init__(self) -> None:
        self.lignes_lues = 0
        self.lignes_rejetees = 0
        self.erreurs: list[tuple[int, str]] = []
        self.etiquette_presente = False

    def __repr__(self) -> str:
        return (
            f"RapportLecture(lues={self.lignes_lues}, rejetees={self.lignes_rejetees}, "
            f"etiquette_presente={self.etiquette_presente})"
        )


def lire_transactions(
    chemin: str | Path,
    *,
    strict: bool = False,
    rapport: RapportLecture | None = None,
    max_erreurs_conservees: int = 100,
) -> Iterator[Transaction]:
    """Générateur : lit le CSV ligne à ligne et produit des transactions validées.

    Args:
        chemin: fichier CSV au format de l'annexe A (l'étiquette est facultative).
        strict: si vrai, la première ligne invalide lève :class:`DonneesInvalides` ;
            sinon elle est journalisée, comptée et ignorée (comportement voulu
            pour la commande ``detecter`` sur un fichier inconnu).
        rapport: objet facultatif dans lequel les compteurs sont renseignés.
        max_erreurs_conservees: nombre maximal de messages d'erreur conservés.

    Raises:
        DonneesInvalides: fichier absent, en-tête incomplet, ou ligne invalide en mode strict.
    """
    chemin = Path(chemin)
    if not chemin.is_file():
        raise DonneesInvalides(f"Fichier introuvable : {chemin}")
    rapport = rapport if rapport is not None else RapportLecture()
    # utf-8-sig : tolère un BOM (fichiers enregistrés depuis Excel).
    with chemin.open(newline="", encoding="utf-8-sig") as fichier:
        lecteur = csv.DictReader(fichier)
        entete = [c.strip() for c in (lecteur.fieldnames or [])]
        lecteur.fieldnames = entete
        manquantes = [c for c in COLONNES_OBLIGATOIRES if c not in entete]
        if manquantes:
            raise DonneesInvalides(
                f"{chemin.name} : colonnes absentes de l'en-tête : {', '.join(manquantes)}"
            )
        rapport.etiquette_presente = "est_fraude" in entete
        for ligne in lecteur:
            numero = lecteur.line_num  # numéro physique (les lignes vides sont sautées par csv)
            if not any((v or "").strip() for k, v in ligne.items() if k is not None):
                continue  # ligne vide
            try:
                transaction = Transaction.depuis_ligne(ligne)
            except DonneesInvalides as erreur:
                if strict:
                    raise DonneesInvalides(f"{chemin.name}, ligne {numero} : {erreur}") from erreur
                rapport.lignes_rejetees += 1
                if len(rapport.erreurs) < max_erreurs_conservees:
                    rapport.erreurs.append((numero, str(erreur)))
                # Les premières lignes invalides sont signalées, les suivantes
                # seulement journalisées en DEBUG (pas d'inondation de la console).
                niveau = logging.WARNING if rapport.lignes_rejetees <= 10 else logging.DEBUG
                journal.log(niveau, "%s, ligne %d ignorée : %s", chemin.name, numero, erreur)
                continue
            rapport.lignes_lues += 1
            yield transaction


def lire_par_blocs(
    chemin: str | Path,
    taille_bloc: int = 10_000,
    *,
    strict: bool = False,
    rapport: RapportLecture | None = None,
) -> Iterator[list[Transaction]]:
    """Générateur : produit des listes d'au plus ``taille_bloc`` transactions.

    La mémoire utilisée est bornée par la taille d'un bloc, quelle que soit
    la taille du fichier. Le dernier bloc peut être plus court.

    Raises:
        ParametreInvalide: si ``taille_bloc`` n'est pas un entier strictement positif.
    """
    if not isinstance(taille_bloc, int) or isinstance(taille_bloc, bool) or taille_bloc <= 0:
        raise ParametreInvalide(f"taille_bloc doit être un entier > 0 (reçu : {taille_bloc!r})")
    flux = lire_transactions(chemin, strict=strict, rapport=rapport)
    while bloc := list(islice(flux, taille_bloc)):
        yield bloc


class FenetreGlissanteParCompte:
    """Itérateur : pour chaque transaction, la fenêtre des dernières transactions du même compte.

    Pour chaque transaction ``t`` du flux d'entrée (supposé chronologique),
    l'itérateur produit le couple ``(compte, fenetre)`` où ``fenetre`` est un
    tuple des au plus ``taille`` dernières transactions de ce compte, ``t``
    comprise et en dernière position.

    Comportement aux bords :

    * **début** : tant qu'un compte n'a pas encore ``taille`` transactions,
      la fenêtre est partielle (plus courte) ; avec ``completes_seulement=True``
      ces fenêtres partielles ne sont pas produites ;
    * **fin** : l'itération s'arrête (``StopIteration``) dès que le flux
      d'entrée est épuisé ; aucune fenêtre n'est produite « à vide ».

    Si ``duree`` est fournie, les transactions plus anciennes que
    ``t.horodatage - duree`` sortent de la fenêtre (fenêtre temporelle).

    Args:
        transactions: flux de transactions trié chronologiquement.
        taille: nombre maximal de transactions par fenêtre (>= 1).
        duree: durée maximale couverte par la fenêtre, ou ``None``.
        cle: fonction donnant le compte d'une transaction (émetteur par défaut).
        completes_seulement: ne produire que les fenêtres de ``taille`` éléments.
    """

    def __init__(
        self,
        transactions: Iterable[Transaction],
        taille: int = 5,
        duree: timedelta | None = None,
        cle: Callable[[Transaction], str] = lambda t: t.id_emetteur,
        completes_seulement: bool = False,
    ) -> None:
        if not isinstance(taille, int) or isinstance(taille, bool) or taille < 1:
            raise ParametreInvalide(f"taille doit être un entier >= 1 (reçu : {taille!r})")
        if duree is not None and duree <= timedelta(0):
            raise ParametreInvalide("duree doit être strictement positive")
        self._source = iter(transactions)
        self._taille = taille
        self._duree = duree
        self._cle = cle
        self._completes_seulement = completes_seulement
        self._fenetres: dict[str, deque[Transaction]] = {}

    def __iter__(self) -> FenetreGlissanteParCompte:
        return self

    def __next__(self) -> tuple[str, tuple[Transaction, ...]]:
        while True:
            transaction = next(self._source)  # propage StopIteration en fin de flux
            compte = self._cle(transaction)
            fenetre = self._fenetres.setdefault(compte, deque(maxlen=self._taille))
            fenetre.append(transaction)
            if self._duree is not None:
                limite = transaction.horodatage - self._duree
                while fenetre and fenetre[0].horodatage < limite:
                    fenetre.popleft()
            if self._completes_seulement and len(fenetre) < self._taille:
                continue
            return compte, tuple(fenetre)
