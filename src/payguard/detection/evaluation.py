"""Évaluation du moteur, écrite à la main : matrice de confusion, taux, coût métier.

Pourquoi l'exactitude (*accuracy*) ne suffit pas : avec environ 1,5 % de
fraudes, un « détecteur » qui ne signale **jamais** rien obtient 98,5 %
d'exactitude tout en laissant passer 100 % des fraudes. L'exactitude est
dominée par la classe majoritaire ; elle ne dit rien de ce qui compte ici
(les fraudes trouvées, celles manquées, le travail inutile imposé aux
analystes). On mesure donc séparément détections, manques et fausses
alertes, et surtout le **coût métier** :

* une fraude non détectée coûte son montant ;
* une alerte injustifiée coûte 500 GNF de traitement.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Collection, Iterable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from payguard.comptes.transaction import Transaction
from payguard.detection.alerte import Evaluation
from payguard.exceptions import DonneesInvalides, ParametreInvalide

#: Coût de traitement d'une alerte injustifiée (GNF), fixé par le sujet.
COUT_FAUSSE_ALERTE = 500


def _ratio(numerateur: float, denominateur: float) -> float:
    return numerateur / denominateur if denominateur else 0.0


@dataclass(frozen=True, slots=True)
class MatriceConfusion:
    """Comptage des quatre issues possibles (la classe « positive » est la fraude)."""

    vrais_positifs: int
    faux_negatifs: int
    faux_positifs: int
    vrais_negatifs: int

    @property
    def fraudes_detectees(self) -> int:
        """Fraudes signalées (vrais positifs)."""
        return self.vrais_positifs

    @property
    def fraudes_manquees(self) -> int:
        """Fraudes non signalées (faux négatifs)."""
        return self.faux_negatifs

    @property
    def fausses_alertes(self) -> int:
        """Transactions légitimes signalées (faux positifs)."""
        return self.faux_positifs

    @property
    def total(self) -> int:
        """Nombre total de transactions évaluées."""
        return self.vrais_positifs + self.faux_negatifs + self.faux_positifs + self.vrais_negatifs

    @property
    def nb_fraudes(self) -> int:
        """Nombre de fraudes réelles."""
        return self.vrais_positifs + self.faux_negatifs

    @property
    def nb_alertes(self) -> int:
        """Nombre de transactions signalées."""
        return self.vrais_positifs + self.faux_positifs

    @property
    def taux_detection(self) -> float:
        """Part des fraudes détectées (rappel) ; 0 s'il n'y a aucune fraude."""
        return _ratio(self.vrais_positifs, self.nb_fraudes)

    @property
    def precision(self) -> float:
        """Part des alertes qui sont de vraies fraudes ; 0 s'il n'y a aucune alerte."""
        return _ratio(self.vrais_positifs, self.nb_alertes)

    @property
    def taux_fausses_alertes(self) -> float:
        """Part des transactions légitimes signalées à tort."""
        return _ratio(self.faux_positifs, self.faux_positifs + self.vrais_negatifs)

    @property
    def taux_alerte(self) -> float:
        """Part de toutes les transactions qui sont signalées (charge de travail)."""
        return _ratio(self.nb_alertes, self.total)

    @property
    def exactitude(self) -> float:
        """Exactitude (accuracy) — fournie pour montrer qu'elle est trompeuse."""
        return _ratio(self.vrais_positifs + self.vrais_negatifs, self.total)

    @property
    def f1(self) -> float:
        """Moyenne harmonique de la précision et du taux de détection."""
        return _ratio(
            2 * self.precision * self.taux_detection, self.precision + self.taux_detection
        )


@dataclass(frozen=True, slots=True)
class RapportEvaluation:
    """Résultat complet de l'évaluation d'un réglage."""

    nom: str
    matrice: MatriceConfusion
    cout_fraudes_manquees: int
    cout_fausses_alertes: int
    montant_fraudes_total: int

    @property
    def cout_total(self) -> int:
        """Coût métier total (GNF)."""
        return self.cout_fraudes_manquees + self.cout_fausses_alertes

    @property
    def montant_fraudes_detectees(self) -> int:
        """Montant des fraudes interceptées (GNF)."""
        return self.montant_fraudes_total - self.cout_fraudes_manquees

    @property
    def cout_relatif(self) -> float:
        """Coût rapporté à celui d'une absence totale de détection (1,0 = aucun gain)."""
        return _ratio(self.cout_total, self.montant_fraudes_total)

    def vers_dict(self) -> dict[str, Any]:
        """Vue à plat (pour un tableau ou un JSON)."""
        m = self.matrice
        return {
            "reglage": self.nom,
            "alertes": m.nb_alertes,
            "fraudes_detectees": m.fraudes_detectees,
            "fraudes_manquees": m.fraudes_manquees,
            "fausses_alertes": m.fausses_alertes,
            "taux_detection": m.taux_detection,
            "precision": m.precision,
            "taux_alerte": m.taux_alerte,
            "exactitude": m.exactitude,
            "cout_fraudes_manquees": self.cout_fraudes_manquees,
            "cout_fausses_alertes": self.cout_fausses_alertes,
            "cout_total": self.cout_total,
            "cout_relatif": self.cout_relatif,
        }


def _transactions(elements: Iterable[Transaction | Evaluation]) -> Iterable[Transaction]:
    for element in elements:
        yield element.transaction if isinstance(element, Evaluation) else element


def evaluer(
    transactions: Iterable[Transaction | Evaluation],
    ids_signales: Collection[str],
    *,
    nom: str = "",
    cout_fausse_alerte: int = COUT_FAUSSE_ALERTE,
) -> RapportEvaluation:
    """Compare les signalements aux étiquettes et calcule le coût métier.

    Args:
        transactions: transactions étiquetées (ou évaluations du moteur).
        ids_signales: identifiants des transactions signalées.
        nom: libellé du réglage évalué.
        cout_fausse_alerte: coût d'une alerte injustifiée (GNF).

    Raises:
        DonneesInvalides: si une transaction n'a pas d'étiquette.
        ParametreInvalide: si le coût d'une fausse alerte est négatif.
    """
    if cout_fausse_alerte < 0:
        raise ParametreInvalide("cout_fausse_alerte doit être positif ou nul")
    signales = (
        ids_signales if isinstance(ids_signales, (set, frozenset, dict)) else set(ids_signales)
    )
    vp = fn = fp = vn = 0
    cout_manquees = montant_fraudes = 0
    for transaction in _transactions(transactions):
        if transaction.est_fraude is None:
            raise DonneesInvalides(
                f"Transaction {transaction.id_transaction} sans étiquette : évaluation impossible"
            )
        signalee = transaction.id_transaction in signales
        if transaction.est_fraude:
            montant_fraudes += transaction.montant
            if signalee:
                vp += 1
            else:
                fn += 1
                cout_manquees += transaction.montant
        elif signalee:
            fp += 1
        else:
            vn += 1
    return RapportEvaluation(
        nom,
        MatriceConfusion(vp, fn, fp, vn),
        cout_manquees,
        fp * cout_fausse_alerte,
        montant_fraudes,
    )


def evaluer_seuils(
    evaluations: Sequence[Evaluation],
    seuils: Iterable[float],
    *,
    prefixe: str = "seuil",
    cout_fausse_alerte: int = COUT_FAUSSE_ALERTE,
) -> list[RapportEvaluation]:
    """Évalue plusieurs seuils d'alerte à partir des mêmes scores (sans relancer les règles)."""
    rapports = []
    for seuil in seuils:
        signales = {e.transaction.id_transaction for e in evaluations if e.est_alerte(seuil)}
        rapports.append(
            evaluer(
                evaluations,
                signales,
                nom=f"{prefixe} {seuil:g}",
                cout_fausse_alerte=cout_fausse_alerte,
            )
        )
    return rapports


def references(
    transactions: Sequence[Transaction | Evaluation], cout_fausse_alerte: int = COUT_FAUSSE_ALERTE
) -> list[RapportEvaluation]:
    """Deux stratégies de référence : ne rien signaler / tout signaler."""
    liste = list(_transactions(transactions))
    return [
        evaluer(
            liste, set(), nom="référence : aucune alerte", cout_fausse_alerte=cout_fausse_alerte
        ),
        evaluer(
            liste,
            {t.id_transaction for t in liste},
            nom="référence : tout signaler",
            cout_fausse_alerte=cout_fausse_alerte,
        ),
    ]


def detection_par_scenario(
    evaluations: Iterable[Evaluation | Transaction],
    ids_signales: Collection[str],
    scenarios: Mapping[str, str],
) -> dict[str, dict[str, float]]:
    """Taux de détection par scénario de fraude (nécessite le fichier annexe des scénarios)."""
    signales = set(ids_signales)
    comptes: dict[str, list[int]] = defaultdict(
        lambda: [0, 0, 0]
    )  # total, détectées, montant manqué
    for transaction in _transactions(evaluations):
        scenario = scenarios.get(transaction.id_transaction)
        if scenario is None:
            continue
        compte = comptes[scenario]
        compte[0] += 1
        if transaction.id_transaction in signales:
            compte[1] += 1
        else:
            compte[2] += transaction.montant
    return {
        scenario: {
            "fraudes": total,
            "detectees": detectees,
            "taux_detection": _ratio(detectees, total),
            "montant_manque": manque,
        }
        for scenario, (total, detectees, manque) in sorted(comptes.items())
    }


def contribution_des_regles(
    evaluations: Iterable[Evaluation], seuil: float
) -> dict[str, dict[str, int]]:
    """Pour chaque règle : déclenchements sur fraudes et sur
    légitimes, parmi les transactions signalées."""
    resultat: dict[str, dict[str, int]] = defaultdict(
        lambda: {"sur_fraudes": 0, "sur_legitimes": 0}
    )
    for evaluation in evaluations:
        if not evaluation.est_alerte(seuil):
            continue
        cle = "sur_fraudes" if evaluation.transaction.est_fraude else "sur_legitimes"
        for regle in evaluation.regles:
            resultat[regle][cle] += 1
    return dict(sorted(resultat.items()))


def evolution_mensuelle(
    evaluations: Iterable[Evaluation], seuil: float, cout_fausse_alerte: int = COUT_FAUSSE_ALERTE
) -> list[RapportEvaluation]:
    """Coût et taux de détection du moteur mois par mois (extension facultative)."""
    par_mois: dict[str, list[Evaluation]] = defaultdict(list)
    for evaluation in evaluations:
        par_mois[evaluation.transaction.horodatage.strftime("%Y-%m")].append(evaluation)
    rapports = []
    for mois in sorted(par_mois):
        liste = par_mois[mois]
        signales = {e.transaction.id_transaction for e in liste if e.est_alerte(seuil)}
        rapports.append(evaluer(liste, signales, nom=mois, cout_fausse_alerte=cout_fausse_alerte))
    return rapports
