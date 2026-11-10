"""Le :class:`MoteurDeRegles` : applique une liste de règles
interchangeables (patron Stratégie)."""

from __future__ import annotations

import logging
from collections.abc import Iterable, Iterator

from payguard.comptes.transaction import Transaction
from payguard.detection.alerte import Alerte, Evaluation
from payguard.detection.base import Regle, valider_nombre
from payguard.donnees.profils import ProfilCompte, ProfilsComptes
from payguard.exceptions import ParametreInvalide

journal = logging.getLogger(__name__)


class MoteurDeRegles:
    """Moteur de détection : score = somme des poids des règles déclenchées.

    Le moteur ne connaît que l'interface :class:`~payguard.detection.base.Regle` ;
    ajouter, retirer ou remplacer une règle (:meth:`ajouter_regle`,
    :meth:`retirer_regle`) ne demande aucune modification de cette classe.

    **Profils causaux.** :meth:`analyser` parcourt les transactions dans
    l'ordre chronologique ; chaque transaction est évaluée avec le profil de
    son émetteur *avant* elle, puis le profil est mis à jour. Aucune
    information future (et a fortiori aucune étiquette) n'influence une
    décision : le moteur fonctionne à l'identique sur un fichier inconnu,
    et peut traiter un flux sans le charger en mémoire.

    Args:
        regles: règles initiales.
        seuil_alerte: score à partir duquel une transaction est signalée (> 0).
    """

    def __init__(self, regles: Iterable[Regle] = (), seuil_alerte: float = 1.0) -> None:
        self._regles: list[Regle] = []
        self.seuil_alerte = seuil_alerte
        for regle in regles:
            self.ajouter_regle(regle)

    # -- configuration ---------------------------------------------------

    @property
    def seuil_alerte(self) -> float:
        """Score minimal d'une alerte."""
        return self._seuil_alerte

    @seuil_alerte.setter
    def seuil_alerte(self, valeur: float) -> None:
        self._seuil_alerte = valider_nombre(
            "seuil_alerte", valeur, minimum=0.0, strict_minimum=True
        )

    @property
    def regles(self) -> tuple[Regle, ...]:
        """Règles actives, dans l'ordre d'application."""
        return tuple(self._regles)

    def ajouter_regle(self, regle: Regle) -> None:
        """Ajoute une règle.

        Raises:
            TypeError: si l'objet n'est pas une :class:`Regle`.
            ParametreInvalide: si une règle de même nom est déjà présente.
        """
        if not isinstance(regle, Regle):
            raise TypeError(f"Une règle doit hériter de Regle (reçu : {type(regle).__name__})")
        if regle.identifiant in self:
            raise ParametreInvalide(
                f"La règle {regle.identifiant!r} est déjà présente dans le moteur"
            )
        self._regles.append(regle)

    def retirer_regle(self, nom: str) -> Regle:
        """Retire et renvoie la règle d'identifiant ``nom`` (lève
        ``KeyError`` si elle est absente)."""
        for indice, regle in enumerate(self._regles):
            if regle.identifiant == nom:
                return self._regles.pop(indice)
        raise KeyError(nom)

    # -- évaluation ------------------------------------------------------

    def evaluer(self, transaction: Transaction, profil: ProfilCompte | None = None) -> Evaluation:
        """Applique toutes les règles à une transaction, sans modifier le profil."""
        profil = profil if profil is not None else ProfilCompte(transaction.id_emetteur)
        declenchements = []
        for regle in self._regles:
            if regle.concerne(transaction):
                resultat = regle.evaluer(transaction, profil)
                if resultat.declenchee:
                    declenchements.append(resultat)
        score = sum(r.poids for r in declenchements)
        return Evaluation(transaction, score, tuple(declenchements))

    def analyser(
        self,
        transactions: Iterable[Transaction],
        profils: ProfilsComptes | None = None,
    ) -> Iterator[Evaluation]:
        """Générateur : évalue chaque transaction puis intègre la transaction aux profils.

        Args:
            transactions: flux **chronologique** de transactions.
            profils: historique de référence facultatif (copié, jamais modifié).
                Sans lui, les profils sont construits à partir du flux lui-même.
        """
        courants = profils.copie() if profils is not None else ProfilsComptes()
        derniere = None
        hors_ordre = 0
        for transaction in transactions:
            if derniere is not None and transaction.horodatage < derniere:
                hors_ordre += 1
            derniere = transaction.horodatage
            emetteur = courants.obtenir_ou_creer(transaction.id_emetteur)
            yield self.evaluer(transaction, emetteur)
            emetteur.enregistrer_emission(transaction)
            courants.obtenir_ou_creer(transaction.id_destinataire).enregistrer_reception(
                transaction
            )
        if hors_ordre:
            journal.warning(
                "%d transactions n'étaient pas dans l'ordre "
                "chronologique : triez le flux avant l'analyse",
                hors_ordre,
            )

    def detecter(
        self,
        transactions: Iterable[Transaction],
        profils: ProfilsComptes | None = None,
    ) -> Iterator[Alerte]:
        """Générateur des seules alertes (score >= :attr:`seuil_alerte`), au fil de l'eau."""
        for evaluation in self.analyser(transactions, profils):
            if evaluation.est_alerte(self._seuil_alerte):
                yield Alerte.depuis_evaluation(evaluation)

    # -- méthodes spéciales ------------------------------------------------

    def __len__(self) -> int:
        return len(self._regles)

    def __iter__(self) -> Iterator[Regle]:
        return iter(self._regles)

    def __contains__(self, nom: object) -> bool:
        return any(r.identifiant == nom for r in self._regles)

    def __repr__(self) -> str:
        noms = ", ".join(r.identifiant for r in self._regles)
        return f"MoteurDeRegles(seuil_alerte={self._seuil_alerte:g}, regles=[{noms}])"
