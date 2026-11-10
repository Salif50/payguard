"""Résultats du moteur : :class:`Evaluation` (toute transaction)
et :class:`Alerte` (transaction signalée)."""

from __future__ import annotations

from dataclasses import dataclass
from functools import total_ordering

from payguard.comptes.transaction import Transaction
from payguard.detection.base import ResultatRegle
from payguard.exceptions import ParametreInvalide


@dataclass(frozen=True, slots=True)
class Evaluation:
    """Verdict du moteur sur une transaction, qu'elle soit signalée ou non.

    Conserver le score de **toutes** les transactions permet d'évaluer
    plusieurs seuils d'alerte sans relancer les règles.
    """

    transaction: Transaction
    score: float
    declenchements: tuple[ResultatRegle, ...] = ()

    @property
    def regles(self) -> tuple[str, ...]:
        """Noms des règles déclenchées."""
        return tuple(r.regle for r in self.declenchements)

    @property
    def motifs(self) -> tuple[str, ...]:
        """Motifs lisibles des règles déclenchées."""
        return tuple(r.motif for r in self.declenchements)

    def est_alerte(self, seuil: float) -> bool:
        """Vrai si le score atteint le seuil (et qu'au moins une règle s'est déclenchée)."""
        return bool(self.declenchements) and self.score >= seuil


@total_ordering
@dataclass(frozen=True, slots=True)
class Alerte:
    """Transaction signalée : la transaction, son score et les motifs qui l'expliquent.

    Le score est la somme des poids des règles déclenchées. L'ordre naturel
    (``sorted(alertes, reverse=True)``) classe de la plus suspecte à la
    moins suspecte.
    """

    transaction: Transaction
    score: float
    regles: tuple[str, ...]
    motifs: tuple[str, ...]

    def __post_init__(self) -> None:
        if self.score < 0:
            raise ParametreInvalide("Le score d'une alerte ne peut pas être négatif")
        if len(self.regles) != len(self.motifs):
            raise ParametreInvalide("Chaque règle déclenchée doit avoir un motif")
        if not self.regles:
            raise ParametreInvalide("Une alerte doit être justifiée par au moins une règle")

    @classmethod
    def depuis_evaluation(cls, evaluation: Evaluation) -> Alerte:
        """Construit l'alerte correspondant à une évaluation."""
        return cls(evaluation.transaction, evaluation.score, evaluation.regles, evaluation.motifs)

    @property
    def id_transaction(self) -> str:
        """Identifiant de la transaction signalée."""
        return self.transaction.id_transaction

    def __lt__(self, autre: object) -> bool:
        if not isinstance(autre, Alerte):
            return NotImplemented
        return (self.score, self.transaction.id_transaction) < (
            autre.score,
            autre.transaction.id_transaction,
        )

    def __str__(self) -> str:
        t = self.transaction
        entete = (
            f"[ALERTE] {t.id_transaction} | {t.horodatage:%Y-%m-%d %H:%M:%S} | {t.type.value} | "
            f"{t.montant:,} GNF | {t.id_emetteur} -> {t.id_destinataire} | score {self.score:g}"
        ).replace(",", " ")
        details = "\n".join(
            f"    - {regle} : {motif}" for regle, motif in zip(self.regles, self.motifs)
        )
        return f"{entete}\n{details}"

    def vers_ligne(self) -> dict[str, str]:
        """Ligne CSV du fichier d'alertes produit par la commande ``detecter``."""
        t = self.transaction
        return {
            "id_transaction": t.id_transaction,
            "horodatage": t.horodatage.isoformat(timespec="seconds"),
            "id_emetteur": t.id_emetteur,
            "id_destinataire": t.id_destinataire,
            "type": t.type.value,
            "montant": str(t.montant),
            "score": f"{self.score:g}",
            "regles": "|".join(self.regles),
            "motifs": " ; ".join(self.motifs),
        }


COLONNES_ALERTES: tuple[str, ...] = (
    "id_transaction",
    "horodatage",
    "id_emetteur",
    "id_destinataire",
    "type",
    "montant",
    "score",
    "regles",
    "motifs",
)
