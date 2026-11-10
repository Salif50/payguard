"""Règles concrètes de détection, chacune paramétrable par ses seuils.

Chaque règle couvre un ou plusieurs scénarios de fraude de la phase 1 :

=========================  ===============================================
Règle                      Scénario(s) visé(s)
=========================  ===============================================
``montant_anormal``        montant très supérieur aux habitudes du compte
``montant_eleve``          tout montant élevé (coût d'une fraude manquée)
``rafale``                 rafale de transactions en quelques minutes
``horaire_inhabituel``     horaire inhabituel (nuit)
``changement_zone``        changement brutal de zone géographique
``nouvel_appareil``        utilisation d'un nouvel appareil
``compte_recent_vide``     compte récemment créé qui se vide aussitôt
=========================  ===============================================

Toutes les règles ne lisent que la transaction courante et le profil
**passé** de son émetteur : jamais l'étiquette ``est_fraude``.
"""

from __future__ import annotations

from collections.abc import Iterable
from datetime import timedelta

from payguard.comptes.transaction import Transaction
from payguard.detection.base import Regle, ResultatRegle, formater_gnf, valider_nombre
from payguard.donnees.profils import ProfilCompte
from payguard.exceptions import ParametreInvalide


class RegleMontantAnormal(Regle):
    """Montant nettement supérieur à la moyenne **et** au maximum passé du compte.

    Args:
        facteur: rapport minimal montant / montant moyen.
        min_operations: historique minimal pour que la moyenne ait un sens.
        montant_minimum: en dessous, on ne signale pas (enjeu trop faible).
    """

    nom = "montant_anormal"
    description = "Montant très supérieur aux habitudes du compte"

    def __init__(
        self,
        poids: float = 1.0,
        facteur: float = 4.0,
        min_operations: int = 3,
        montant_minimum: int = 100_000,
        types_operations: Iterable[str] | None = None,
        *,
        identifiant: str | None = None,
    ) -> None:
        super().__init__(poids, types_operations, identifiant=identifiant)
        self.facteur = valider_nombre("facteur", facteur, minimum=1.0, strict_minimum=True)
        self.min_operations = valider_nombre(
            "min_operations", min_operations, minimum=1, entier=True
        )
        self.montant_minimum = valider_nombre(
            "montant_minimum", montant_minimum, minimum=0, entier=True
        )

    def evaluer(self, transaction: Transaction, profil: ProfilCompte) -> ResultatRegle:
        if (
            profil.nb_operations < self.min_operations
            or transaction.montant < self.montant_minimum
        ):
            return self._ignorer()
        moyenne = profil.montant_moyen
        if (
            transaction.montant >= self.facteur * moyenne
            and transaction.montant > profil.montant_max
        ):
            return self._declencher(
                f"montant {formater_gnf(transaction.montant)} = "
                f"{transaction.montant / moyenne:.1f} × "
                f"la moyenne du compte ({formater_gnf(moyenne)}), au-delà de son maximum "
                f"({formater_gnf(profil.montant_max)})"
            )
        return self._ignorer()


class RegleMontantEleve(Regle):
    """Montant élevé dans l'absolu, quel que soit l'historique.

    Utile pour les comptes sans historique (premières opérations du fichier)
    et justifiée par le coût métier : une fraude manquée coûte son montant,
    une alerte injustifiée seulement 500 GNF.

    Args:
        seuil: montant (GNF) à partir duquel la règle se déclenche.
    """

    nom = "montant_eleve"
    description = "Montant élevé dans l'absolu"

    def __init__(
        self,
        poids: float = 1.0,
        seuil: int = 2_000_000,
        types_operations: Iterable[str] | None = None,
        *,
        identifiant: str | None = None,
    ) -> None:
        super().__init__(poids, types_operations, identifiant=identifiant)
        self.seuil = valider_nombre("seuil", seuil, minimum=1, entier=True)

    def evaluer(self, transaction: Transaction, profil: ProfilCompte) -> ResultatRegle:
        if transaction.montant >= self.seuil:
            return self._declencher(
                f"montant {formater_gnf(transaction.montant)} >= seuil de "
                f"{formater_gnf(self.seuil)}"
            )
        return self._ignorer()


class RegleRafale(Regle):
    """Au moins ``nb_operations`` opérations émises par le compte en ``fenetre_minutes`` minutes.

    Args:
        nb_operations: nombre d'opérations (courante comprise) qui constitue une rafale.
        fenetre_minutes: durée de la fenêtre glissante.
    """

    nom = "rafale"
    description = "Rafale de transactions en quelques minutes"

    def __init__(
        self,
        poids: float = 1.0,
        nb_operations: int = 3,
        fenetre_minutes: float = 10.0,
        types_operations: Iterable[str] | None = None,
        *,
        identifiant: str | None = None,
    ) -> None:
        super().__init__(poids, types_operations, identifiant=identifiant)
        self.nb_operations = valider_nombre("nb_operations", nb_operations, minimum=2, entier=True)
        self.fenetre_minutes = valider_nombre(
            "fenetre_minutes", fenetre_minutes, minimum=0, strict_minimum=True
        )
        self._fenetre = timedelta(minutes=self.fenetre_minutes)

    def evaluer(self, transaction: Transaction, profil: ProfilCompte) -> ResultatRegle:
        recentes = profil.nb_operations_recentes(transaction.horodatage, self._fenetre) + 1
        if recentes >= self.nb_operations:
            return self._declencher(
                f"{recentes} opérations émises en moins de {self.fenetre_minutes:g} minutes"
            )
        return self._ignorer()


class RegleHoraireInhabituel(Regle):
    """Opération dans une plage horaire où le compte n'opère (presque) jamais.

    Args:
        heure_debut: début de la plage surveillée (inclus, 0-23).
        heure_fin: fin de la plage (exclue, 0-24) ; peut passer minuit.
        part_max: au-delà de cette part d'opérations passées dans la plage,
            le compte est considéré comme habitué à cet horaire.
    """

    nom = "horaire_inhabituel"
    description = "Horaire inhabituel pour le compte"

    def __init__(
        self,
        poids: float = 1.0,
        heure_debut: int = 0,
        heure_fin: int = 5,
        part_max: float = 0.1,
        types_operations: Iterable[str] | None = None,
        *,
        identifiant: str | None = None,
    ) -> None:
        super().__init__(poids, types_operations, identifiant=identifiant)
        self.heure_debut = valider_nombre(
            "heure_debut", heure_debut, minimum=0, maximum=23, entier=True
        )
        self.heure_fin = valider_nombre("heure_fin", heure_fin, minimum=0, maximum=24, entier=True)
        if self.heure_debut == self.heure_fin:
            raise ParametreInvalide("heure_debut et heure_fin doivent différer")
        self.part_max = valider_nombre("part_max", part_max, minimum=0.0, maximum=1.0)

    def _dans_plage(self, heure: int) -> bool:
        if self.heure_debut < self.heure_fin:
            return self.heure_debut <= heure < self.heure_fin
        return heure >= self.heure_debut or heure < self.heure_fin

    def evaluer(self, transaction: Transaction, profil: ProfilCompte) -> ResultatRegle:
        if not self._dans_plage(transaction.heure):
            return self._ignorer()
        part = profil.part_heures(self.heure_debut, self.heure_fin)
        if part <= self.part_max:
            return self._declencher(
                f"opération à {transaction.horodatage:%H:%M}, "
                f"plage {self.heure_debut} h-{self.heure_fin} h "
                f"représentant {part:.0%} de l'historique du compte"
            )
        return self._ignorer()


class RegleChangementZone(Regle):
    """Changement brutal de zone : « voyage impossible » ou zone jamais fréquentée.

    Se déclenche si :

    * la dernière opération du compte a eu lieu dans une **autre** zone il y
      a moins de ``delai_minutes`` (déplacement physiquement improbable) ; ou
    * le compte a un historique suffisant (``min_operations``) et la zone
      représente moins de ``part_min`` de ses opérations.
    """

    nom = "changement_zone"
    description = "Changement brutal de zone géographique"

    def __init__(
        self,
        poids: float = 1.0,
        delai_minutes: float = 180.0,
        min_operations: int = 5,
        part_min: float = 0.0,
        types_operations: Iterable[str] | None = None,
        *,
        identifiant: str | None = None,
    ) -> None:
        super().__init__(poids, types_operations, identifiant=identifiant)
        self.delai_minutes = valider_nombre(
            "delai_minutes", delai_minutes, minimum=0, strict_minimum=True
        )
        self.min_operations = valider_nombre(
            "min_operations", min_operations, minimum=1, entier=True
        )
        self.part_min = valider_nombre("part_min", part_min, minimum=0.0, maximum=1.0)
        self._delai = timedelta(minutes=self.delai_minutes)

    def evaluer(self, transaction: Transaction, profil: ProfilCompte) -> ResultatRegle:
        if (
            profil.derniere_operation is not None
            and profil.derniere_zone != transaction.zone
            and transaction.horodatage - profil.derniere_operation <= self._delai
        ):
            minutes = (transaction.horodatage - profil.derniere_operation).total_seconds() / 60
            return self._declencher(
                f"opération à {transaction.zone} {minutes:.0f} "
                f"min après une opération à {profil.derniere_zone}"
            )
        if (
            profil.nb_operations >= self.min_operations
            and profil.part_zone(transaction.zone) <= self.part_min
        ):
            return self._declencher(
                f"zone {transaction.zone} jamais ou rarement utilisée par le compte "
                f"({profil.zones[transaction.zone]}/{profil.nb_operations} opérations)"
            )
        return self._ignorer()


class RegleNouvelAppareil(Regle):
    """Opération depuis un appareil jamais utilisé par un compte qui a déjà un historique.

    Args:
        min_operations: historique minimal ; un compte tout neuf n'a pas
            encore d'appareil « habituel ».
    """

    nom = "nouvel_appareil"
    description = "Utilisation d'un nouvel appareil"

    def __init__(
        self,
        poids: float = 1.0,
        min_operations: int = 2,
        types_operations: Iterable[str] | None = None,
        *,
        identifiant: str | None = None,
    ) -> None:
        super().__init__(poids, types_operations, identifiant=identifiant)
        self.min_operations = valider_nombre(
            "min_operations", min_operations, minimum=1, entier=True
        )

    def evaluer(self, transaction: Transaction, profil: ProfilCompte) -> ResultatRegle:
        if profil.nb_operations >= self.min_operations and not profil.connait_appareil(
            transaction.appareil_id
        ):
            return self._declencher(
                f"appareil {transaction.appareil_id} jamais utilisé par le compte "
                f"({len(profil.appareils)} appareil(s) connu(s), "
                f"{profil.nb_operations} opérations)"
            )
        return self._ignorer()


class RegleCompteRecentVide(Regle):
    """Compte apparu récemment qui renvoie aussitôt l'essentiel de ce qu'il a reçu.

    L'ancienneté est mesurée depuis la première apparition du compte dans
    les données (le fichier ne contient pas de date d'ouverture).

    Args:
        anciennete_max_jours: au-delà, le compte n'est plus « récent ».
        part_min: part minimale des fonds disponibles (reçus et non encore
            dépensés, d'après le profil) que l'opération emporte.
        montant_minimum: montant minimal de l'opération (GNF).
    """

    nom = "compte_recent_vide"
    description = "Compte récemment créé qui se vide aussitôt"

    def __init__(
        self,
        poids: float = 1.0,
        anciennete_max_jours: float = 7.0,
        part_min: float = 0.8,
        montant_minimum: int = 50_000,
        types_operations: Iterable[str] | None = None,
        *,
        identifiant: str | None = None,
    ) -> None:
        super().__init__(poids, types_operations, identifiant=identifiant)
        self.anciennete_max_jours = valider_nombre(
            "anciennete_max_jours", anciennete_max_jours, minimum=0, strict_minimum=True
        )
        self.part_min = valider_nombre(
            "part_min", part_min, minimum=0.0, maximum=1.0, strict_minimum=True
        )
        self.montant_minimum = valider_nombre(
            "montant_minimum", montant_minimum, minimum=0, entier=True
        )
        self._anciennete_max = timedelta(days=self.anciennete_max_jours)

    def evaluer(self, transaction: Transaction, profil: ProfilCompte) -> ResultatRegle:
        anciennete = profil.anciennete(transaction.horodatage)
        disponible = profil.solde_estime
        if (
            anciennete is None
            or anciennete > self._anciennete_max
            or disponible <= 0
            or transaction.montant < self.montant_minimum
        ):
            return self._ignorer()
        part = transaction.montant / disponible
        if part >= self.part_min:
            heures = anciennete.total_seconds() / 3600
            return self._declencher(
                f"compte apparu il y a {heures:.1f} h qui "
                f"émet {min(part, 1.0):.0%} des fonds reçus "
                f"et non encore dépensés ({formater_gnf(disponible)})"
            )
        return self._ignorer()


__all__ = [
    "RegleChangementZone",
    "RegleCompteRecentVide",
    "RegleHoraireInhabituel",
    "RegleMontantAnormal",
    "RegleMontantEleve",
    "RegleNouvelAppareil",
    "RegleRafale",
]
