"""Profils de comptes : les habitudes de chaque compte, calculées de deux façons.

:class:`ProfilCompte` regroupe, pour un compte, ce qu'il fait d'habitude en
tant qu'**émetteur** (compte débité) : nombre d'opérations, montant moyen et
maximal, heures, zones et appareils utilisés. Il retient aussi ce que le
compte a **reçu** et la date à laquelle il est apparu pour la première fois,
ce qui permet de repérer un compte récent qui se vide.

:class:`ProfilsComptes` calcule ces profils pour tous les comptes d'un
historique, au choix :

* :meth:`ProfilsComptes.calculer_python` — boucles, dictionnaires et
  ``collections.Counter`` ;
* :meth:`ProfilsComptes.calculer_pandas` — ``groupby`` pandas.

Les deux implémentations produisent des objets **égaux** (``==``), ce que
vérifient les tests et :func:`comparer_implementations`.

Le profil sait aussi se mettre à jour transaction par transaction
(:meth:`ProfilCompte.enregistrer_emission`) : c'est ainsi que le moteur de
détection construit des profils *causaux*, qui ne contiennent jamais que le
passé de la transaction évaluée.
"""

from __future__ import annotations

import copy
import logging
import time
from collections import Counter, deque
from collections.abc import Iterable, Iterator
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import TYPE_CHECKING, Any

from payguard.comptes.transaction import Transaction
from payguard.outils.decorateurs import chronometre

if TYPE_CHECKING:  # pandas n'est importé qu'à l'usage
    import pandas as pd

journal = logging.getLogger(__name__)

#: Nombre d'horodatages récents conservés par compte (détection des rafales).
TAILLE_MEMOIRE_RECENTE = 32


def _deque_recente() -> deque[datetime]:
    return deque(maxlen=TAILLE_MEMOIRE_RECENTE)


@dataclass
class ProfilCompte:
    """Habitudes d'un compte.

    Les champs marqués ``compare=False`` (``recentes``) sont un état de
    travail du moteur de détection, pas une habitude : ils sont exclus de
    l'égalité entre profils.
    """

    id_compte: str
    nb_operations: int = 0
    montant_total: int = 0
    montant_max: int = 0
    heures: Counter[int] = field(default_factory=Counter)
    zones: Counter[str] = field(default_factory=Counter)
    appareils: Counter[str] = field(default_factory=Counter)
    premiere_apparition: datetime | None = None
    derniere_operation: datetime | None = None
    derniere_zone: str | None = None
    nb_receptions: int = 0
    total_recu: int = 0
    recentes: deque[datetime] = field(default_factory=_deque_recente, compare=False, repr=False)

    # -- grandeurs dérivées ----------------------------------------------

    @property
    def montant_moyen(self) -> float:
        """Montant moyen émis (0 si aucune opération)."""
        return self.montant_total / self.nb_operations if self.nb_operations else 0.0

    @property
    def solde_estime(self) -> int:
        """Fonds reçus et non encore dépensés selon les données (reçu - émis).

        Ce n'est pas le vrai solde (le solde initial est inconnu) : pour un
        compte apparu récemment, c'est une bonne estimation de ce qu'il détient.
        """
        return self.total_recu - self.montant_total

    def part_heures(self, debut: int, fin: int) -> float:
        """Part des opérations passées entre ``debut`` (inclus) et ``fin`` (exclu) heures.

        La plage peut passer minuit (``debut=22, fin=5``).
        """
        if not self.nb_operations:
            return 0.0
        if debut <= fin:
            dans_plage = sum(n for h, n in self.heures.items() if debut <= h < fin)
        else:
            dans_plage = sum(n for h, n in self.heures.items() if h >= debut or h < fin)
        return dans_plage / self.nb_operations

    def part_zone(self, zone: str) -> float:
        """Part des opérations réalisées dans ``zone``."""
        return self.zones[zone] / self.nb_operations if self.nb_operations else 0.0

    def zones_habituelles(self, part_minimale: float = 0.1) -> set[str]:
        """Zones représentant au moins ``part_minimale`` des opérations."""
        return {z for z in self.zones if self.part_zone(z) >= part_minimale}

    def appareils_habituels(self) -> set[str]:
        """Appareils déjà utilisés par le compte."""
        return set(self.appareils)

    def connait_appareil(self, appareil_id: str) -> bool:
        """Vrai si l'appareil a déjà servi à une opération de ce compte."""
        return appareil_id in self.appareils

    def anciennete(self, instant: datetime) -> timedelta | None:
        """Durée écoulée depuis la première apparition du compte (``None`` si inconnue)."""
        if self.premiere_apparition is None:
            return None
        return instant - self.premiere_apparition

    def nb_operations_recentes(self, instant: datetime, fenetre: timedelta) -> int:
        """Nombre d'opérations émises dans ``[instant - fenetre ; instant]``."""
        limite = instant - fenetre
        return sum(1 for moment in self.recentes if limite <= moment <= instant)

    # -- mise à jour incrémentale ----------------------------------------

    def _apparaitre(self, instant: datetime) -> None:
        if self.premiere_apparition is None or instant < self.premiere_apparition:
            self.premiere_apparition = instant

    def enregistrer_emission(self, transaction: Transaction) -> None:
        """Intègre une opération émise par le compte."""
        self.nb_operations += 1
        self.montant_total += transaction.montant
        self.montant_max = max(self.montant_max, transaction.montant)
        self.heures[transaction.horodatage.hour] += 1
        self.zones[transaction.zone] += 1
        self.appareils[transaction.appareil_id] += 1
        self._apparaitre(transaction.horodatage)
        if self.derniere_operation is None or transaction.horodatage >= self.derniere_operation:
            self.derniere_operation = transaction.horodatage
            self.derniere_zone = transaction.zone
        self.recentes.append(transaction.horodatage)

    def enregistrer_reception(self, transaction: Transaction) -> None:
        """Intègre une opération reçue par le compte."""
        self.nb_receptions += 1
        self.total_recu += transaction.montant
        self._apparaitre(transaction.horodatage)

    def resume(self) -> dict[str, Any]:
        """Vue « à plat » du profil (pour un DataFrame ou un affichage)."""
        return {
            "id_compte": self.id_compte,
            "nb_operations": self.nb_operations,
            "montant_moyen": round(self.montant_moyen, 2),
            "montant_max": self.montant_max,
            "heure_principale": self.heures.most_common(1)[0][0] if self.heures else None,
            "nb_zones": len(self.zones),
            "zone_principale": self.zones.most_common(1)[0][0] if self.zones else None,
            "nb_appareils": len(self.appareils),
            "nb_receptions": self.nb_receptions,
            "total_recu": self.total_recu,
            "premiere_apparition": self.premiere_apparition,
        }


class ProfilsComptes:
    """Ensemble des profils de comptes, indexé par identifiant de compte."""

    def __init__(self, profils: dict[str, ProfilCompte] | None = None) -> None:
        self._profils: dict[str, ProfilCompte] = dict(profils or {})

    # -- calcul en Python pur --------------------------------------------

    @classmethod
    @chronometre
    def calculer_python(cls, transactions: Iterable[Transaction]) -> ProfilsComptes:
        """Calcule les profils avec des boucles, des dictionnaires et des ``Counter``.

        Les transactions sont d'abord triées (horodatage puis identifiant) pour
        que « la dernière zone » soit définie sans ambiguïté.
        """
        profils: dict[str, ProfilCompte] = {}
        for transaction in sorted(transactions, key=lambda t: (t.horodatage, t.id_transaction)):
            emetteur = profils.get(transaction.id_emetteur)
            if emetteur is None:
                emetteur = profils[transaction.id_emetteur] = ProfilCompte(transaction.id_emetteur)
            emetteur.enregistrer_emission(transaction)
            destinataire = profils.get(transaction.id_destinataire)
            if destinataire is None:
                destinataire = profils[transaction.id_destinataire] = ProfilCompte(
                    transaction.id_destinataire
                )
            destinataire.enregistrer_reception(transaction)
        return cls(profils)

    # -- calcul avec pandas ----------------------------------------------

    @staticmethod
    @chronometre
    def agreger_pandas(df: pd.DataFrame) -> dict[str, Any]:
        """Étape vectorisée du calcul pandas : renvoie les agrégats (DataFrame / Series)."""
        df = df.sort_values(["horodatage", "id_transaction"], kind="stable")
        par_emetteur = df.groupby("id_emetteur", sort=False)
        emissions = par_emetteur.agg(
            nb_operations=("montant", "size"),
            montant_total=("montant", "sum"),
            montant_max=("montant", "max"),
            premiere_emission=("horodatage", "min"),
            derniere_operation=("horodatage", "max"),
            derniere_zone=("zone", "last"),
        )
        receptions = df.groupby("id_destinataire", sort=False).agg(
            nb_receptions=("montant", "size"),
            total_recu=("montant", "sum"),
            premiere_reception=("horodatage", "min"),
        )
        heures = df.groupby([df["id_emetteur"], df["horodatage"].dt.hour.rename("heure")]).size()
        zones = df.groupby(["id_emetteur", "zone"]).size()
        appareils = df.groupby(["id_emetteur", "appareil_id"]).size()
        return {
            "emissions": emissions,
            "receptions": receptions,
            "heures": heures,
            "zones": zones,
            "appareils": appareils,
        }

    @classmethod
    @chronometre
    def calculer_pandas(cls, df: pd.DataFrame) -> ProfilsComptes:
        """Calcule les profils avec ``groupby`` puis les convertit en :class:`ProfilCompte`.

        Args:
            df: DataFrame au format de l'annexe A, colonne ``horodatage`` en
                ``datetime64`` (voir :func:`payguard.donnees.analyse.charger_csv`).
        """
        agregats = cls.agreger_pandas(df)
        profils: dict[str, ProfilCompte] = {}

        def profil(id_compte: str) -> ProfilCompte:
            existant = profils.get(id_compte)
            if existant is None:
                existant = profils[id_compte] = ProfilCompte(id_compte)
            return existant

        for ligne in agregats["emissions"].itertuples():
            p = profil(str(ligne.Index))
            p.nb_operations = int(ligne.nb_operations)
            p.montant_total = int(ligne.montant_total)
            p.montant_max = int(ligne.montant_max)
            p.premiere_apparition = ligne.premiere_emission.to_pydatetime()
            p.derniere_operation = ligne.derniere_operation.to_pydatetime()
            p.derniere_zone = str(ligne.derniere_zone)
        for ligne in agregats["receptions"].itertuples():
            p = profil(str(ligne.Index))
            p.nb_receptions = int(ligne.nb_receptions)
            p.total_recu = int(ligne.total_recu)
            premiere = ligne.premiere_reception.to_pydatetime()
            if p.premiere_apparition is None or premiere < p.premiere_apparition:
                p.premiere_apparition = premiere
        for attribut in ("heures", "zones", "appareils"):
            for (id_compte, valeur), nombre in agregats[attribut].items():
                cle = int(valeur) if attribut == "heures" else str(valeur)
                getattr(profils[str(id_compte)], attribut)[cle] = int(nombre)
        return cls(profils)

    # -- accès -----------------------------------------------------------

    def get(self, id_compte: str) -> ProfilCompte | None:
        """Profil du compte, ou ``None`` s'il est inconnu."""
        return self._profils.get(id_compte)

    def obtenir_ou_creer(self, id_compte: str) -> ProfilCompte:
        """Profil du compte, créé vide s'il n'existe pas encore."""
        profil = self._profils.get(id_compte)
        if profil is None:
            profil = self._profils[id_compte] = ProfilCompte(id_compte)
        return profil

    def copie(self) -> ProfilsComptes:
        """Copie profonde (le moteur met à jour ses profils sans modifier l'original)."""
        return ProfilsComptes(copy.deepcopy(self._profils))

    def differences(self, autre: ProfilsComptes, limite: int = 10) -> list[str]:
        """Liste lisible des écarts avec un autre ensemble de profils (vide si égaux)."""
        ecarts: list[str] = []
        for id_compte in sorted(set(self._profils) | set(autre._profils)):
            a, b = self._profils.get(id_compte), autre._profils.get(id_compte)
            if a != b:
                ecarts.append(f"{id_compte} : {a!r} != {b!r}")
                if len(ecarts) >= limite:
                    break
        return ecarts

    def vers_dataframe(self) -> pd.DataFrame:
        """Tableau récapitulatif (une ligne par compte)."""
        import pandas as pd

        return pd.DataFrame([p.resume() for p in self._profils.values()]).set_index("id_compte")

    def __getitem__(self, id_compte: str) -> ProfilCompte:
        return self._profils[id_compte]

    def __contains__(self, id_compte: object) -> bool:
        return id_compte in self._profils

    def __len__(self) -> int:
        return len(self._profils)

    def __iter__(self) -> Iterator[str]:
        return iter(self._profils)

    def __eq__(self, autre: object) -> bool:
        if not isinstance(autre, ProfilsComptes):
            return NotImplemented
        return self._profils == autre._profils

    __hash__ = None  # type: ignore[assignment]  # objet mutable : non hachable

    def __repr__(self) -> str:
        return f"ProfilsComptes({len(self)} comptes)"


def comparer_implementations(
    transactions: list[Transaction], df: pd.DataFrame, repetitions: int = 3
) -> dict[str, Any]:
    """Vérifie l'égalité des deux calculs puis mesure leurs temps (meilleur de ``repetitions``).

    Les deux implémentations reçoivent des données déjà chargées en mémoire
    (liste de transactions d'une part, DataFrame d'autre part) : on mesure
    le *calcul*, pas la lecture du fichier. Pour pandas, on distingue
    l'agrégation vectorisée seule et le calcul complet (agrégation +
    conversion en objets :class:`ProfilCompte`).

    Returns:
        Dictionnaire : ``identiques``, temps (s) et rapports de vitesse.
    """
    if repetitions < 1:
        raise ValueError("repetitions doit être >= 1")
    temps_python, temps_pandas, temps_agregation = [], [], []
    profils_python = profils_pandas = None
    for _ in range(repetitions):
        debut = time.perf_counter()
        profils_python = ProfilsComptes.calculer_python(transactions)
        temps_python.append(time.perf_counter() - debut)

        debut = time.perf_counter()
        ProfilsComptes.agreger_pandas(df)
        temps_agregation.append(time.perf_counter() - debut)

        debut = time.perf_counter()
        profils_pandas = ProfilsComptes.calculer_pandas(df)
        temps_pandas.append(time.perf_counter() - debut)
    assert profils_python is not None and profils_pandas is not None
    identiques = profils_python == profils_pandas
    if not identiques:
        journal.error("Profils différents : %s", profils_python.differences(profils_pandas, 3))
    meilleur_python, meilleur_pandas, meilleur_agregation = (
        min(temps_python),
        min(temps_pandas),
        min(temps_agregation),
    )
    return {
        "nb_transactions": len(transactions),
        "nb_comptes": len(profils_python),
        "identiques": identiques,
        "repetitions": repetitions,
        "python_s": meilleur_python,
        "pandas_complet_s": meilleur_pandas,
        "pandas_agregation_s": meilleur_agregation,
        "acceleration_complet": meilleur_python / meilleur_pandas,
        "acceleration_agregation": meilleur_python / meilleur_agregation,
    }
