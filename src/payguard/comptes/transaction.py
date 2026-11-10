"""Transaction immuable et énumération des types d'opérations."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from functools import total_ordering

from payguard.exceptions import DonneesInvalides
from payguard.schema import COLONNE_ETIQUETTE, COLONNES_OBLIGATOIRES


class TypeTransaction(StrEnum):
    """Les quatre types d'opérations du système de paiement mobile.

    ``StrEnum`` : chaque membre *est* une chaîne, ce qui simplifie l'écriture
    CSV/SQLite (``TypeTransaction.DEPOT == "depot"``).
    """

    DEPOT = "depot"
    RETRAIT = "retrait"
    TRANSFERT = "transfert"
    PAIEMENT_MARCHAND = "paiement_marchand"

    @classmethod
    def depuis_texte(cls, valeur: str) -> TypeTransaction:
        """Convertit un texte en type, de façon tolérante (casse, espaces, accents usuels).

        Raises:
            DonneesInvalides: si le texte ne correspond à aucun type connu.
        """
        cle = str(valeur).strip().lower().replace("-", "_").replace(" ", "_")
        alias = {
            "dépôt": "depot",
            "paiement": "paiement_marchand",
            "paiement_commercant": "paiement_marchand",
        }
        cle = alias.get(cle, cle)
        try:
            return cls(cle)
        except ValueError:
            raise DonneesInvalides(f"Type d'opération inconnu : {valeur!r}") from None


def _lire_horodatage(texte: str) -> datetime:
    """Lit un horodatage ISO 8601 ; un éventuel fuseau est retiré (heure locale conservée)."""
    try:
        instant = datetime.fromisoformat(texte.strip().replace("Z", "+00:00"))
    except (ValueError, AttributeError):
        raise DonneesInvalides(f"Horodatage invalide : {texte!r}") from None
    return instant.replace(tzinfo=None)


def _lire_montant(texte: str) -> int:
    """Lit un montant entier en GNF (``"1500"`` ou ``"1500.0"`` sont acceptés)."""
    try:
        valeur = float(str(texte).strip().replace(" ", ""))
    except ValueError:
        raise DonneesInvalides(f"Montant invalide : {texte!r}") from None
    if valeur != valeur or valeur <= 0 or valeur == float("inf"):
        raise DonneesInvalides(f"Le montant doit être strictement positif : {texte!r}")
    return int(round(valeur))


def _lire_etiquette(texte: str | None) -> bool | None:
    """Lit la colonne ``est_fraude`` : ``None`` si absente ou vide."""
    if texte is None:
        return None
    cle = str(texte).strip().lower()
    if cle == "":
        return None
    if cle in {"1", "true", "vrai", "oui", "1.0"}:
        return True
    if cle in {"0", "false", "faux", "non", "0.0"}:
        return False
    raise DonneesInvalides(f"Étiquette est_fraude invalide : {texte!r}")


@total_ordering
@dataclass(frozen=True, slots=True)
class Transaction:
    """Opération financière immuable, telle qu'elle figure dans l'historique.

    Une transaction est un *fait* : une fois enregistrée, elle ne change plus.
    La dataclass figée l'impose (toute affectation lève
    ``FrozenInstanceError``) et la rend hachable, donc utilisable dans un
    ensemble ou comme clé de dictionnaire.

    L'ordre naturel est chronologique (puis par identifiant pour départager
    deux opérations simultanées), ce qui permet ``sorted(transactions)``.

    ``est_fraude`` vaut ``None`` quand l'étiquette est inconnue (jeu de test
    de la soutenance). Elle n'est **jamais** lue par le moteur de détection.
    """

    id_transaction: str
    horodatage: datetime
    id_emetteur: str
    id_destinataire: str
    type: TypeTransaction
    montant: int
    zone: str
    appareil_id: str
    est_fraude: bool | None = None

    def __post_init__(self) -> None:
        for nom in ("id_transaction", "id_emetteur", "id_destinataire", "zone", "appareil_id"):
            valeur = getattr(self, nom)
            if not isinstance(valeur, str) or not valeur.strip():
                raise DonneesInvalides(
                    f"Le champ {nom} doit être une chaîne non vide (reçu : {valeur!r})"
                )
        if not isinstance(self.horodatage, datetime):
            raise DonneesInvalides(
                f"horodatage doit être un datetime (reçu : {self.horodatage!r})"
            )
        if not isinstance(self.type, TypeTransaction):
            # Conversion autorisée depuis une chaîne ; frozen impose object.__setattr__.
            object.__setattr__(self, "type", TypeTransaction.depuis_texte(self.type))
        if (
            not isinstance(self.montant, int)
            or isinstance(self.montant, bool)
            or self.montant <= 0
        ):
            raise DonneesInvalides(
                f"Le montant doit être un entier strictement positif (reçu : {self.montant!r})"
            )

    def __lt__(self, autre: object) -> bool:
        if not isinstance(autre, Transaction):
            return NotImplemented
        return (self.horodatage, self.id_transaction) < (autre.horodatage, autre.id_transaction)

    @property
    def heure(self) -> int:
        """Heure (0-23) de l'opération."""
        return self.horodatage.hour

    @classmethod
    def depuis_ligne(cls, ligne: Mapping[str, str | None]) -> Transaction:
        """Construit une transaction depuis une ligne CSV (dictionnaire ``colonne -> texte``).

        Raises:
            DonneesInvalides: si une colonne obligatoire manque ou est mal formée.
        """
        manquantes = [c for c in COLONNES_OBLIGATOIRES if ligne.get(c) in (None, "")]
        if manquantes:
            raise DonneesInvalides(f"Colonnes manquantes ou vides : {', '.join(manquantes)}")
        return cls(
            id_transaction=str(ligne["id_transaction"]).strip(),
            horodatage=_lire_horodatage(str(ligne["horodatage"])),
            id_emetteur=str(ligne["id_emetteur"]).strip(),
            id_destinataire=str(ligne["id_destinataire"]).strip(),
            type=TypeTransaction.depuis_texte(str(ligne["type"])),
            montant=_lire_montant(str(ligne["montant"])),
            zone=str(ligne["zone"]).strip(),
            appareil_id=str(ligne["appareil_id"]).strip(),
            est_fraude=_lire_etiquette(ligne.get(COLONNE_ETIQUETTE)),
        )

    def vers_ligne(self) -> dict[str, str]:
        """Représentation CSV (annexe A) ; l'étiquette inconnue est écrite vide."""
        return {
            "id_transaction": self.id_transaction,
            "horodatage": self.horodatage.isoformat(timespec="seconds"),
            "id_emetteur": self.id_emetteur,
            "id_destinataire": self.id_destinataire,
            "type": self.type.value,
            "montant": str(self.montant),
            "zone": self.zone,
            "appareil_id": self.appareil_id,
            "est_fraude": "" if self.est_fraude is None else str(int(self.est_fraude)),
        }
