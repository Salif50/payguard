"""Hiérarchie des exceptions métier de PayGuard.

Toutes les erreurs levées volontairement par la bibliothèque héritent de
:class:`PayGuardError`, ce qui permet à un appelant (la CLI par exemple) de
les intercepter en un seul ``except`` tout en laissant passer les vraies
erreurs de programmation (``TypeError``, ``AttributeError``...).

Certaines exceptions héritent aussi d'une exception standard
(``ValueError``, ``LookupError``) pour rester compatibles avec le code
Python idiomatique qui intercepte ces types génériques.
"""

from __future__ import annotations


class PayGuardError(Exception):
    """Racine de toutes les erreurs métier de PayGuard."""


# --- Erreurs de paramétrage et de données ---------------------------------


class ParametreInvalide(PayGuardError, ValueError):
    """Un paramètre fourni par l'appelant est invalide (type ou valeur)."""


class DonneesInvalides(PayGuardError, ValueError):
    """Un fichier ou un enregistrement de données ne respecte pas le format attendu."""


class ConfigurationInvalide(PayGuardError, ValueError):
    """La configuration JSON du moteur de règles est invalide."""


class DepotError(PayGuardError):
    """Erreur d'accès à la couche de persistance SQLite."""


# --- Erreurs liées aux comptes et aux opérations ---------------------------


class CompteIntrouvable(PayGuardError, LookupError):
    """Aucun compte ne correspond à l'identifiant demandé."""

    def __init__(self, id_compte: str) -> None:
        super().__init__(f"Compte introuvable : {id_compte!r}")
        self.id_compte = id_compte


class CompteDejaExistant(PayGuardError):
    """Un compte portant le même identifiant est déjà enregistré."""

    def __init__(self, id_compte: str) -> None:
        super().__init__(f"Un compte {id_compte!r} existe déjà")
        self.id_compte = id_compte


class OperationNonAutorisee(PayGuardError):
    """L'opération n'est pas permise pour ce type de compte ou ces paramètres."""


class SoldeInsuffisant(PayGuardError):
    """Le solde du compte ne couvre pas le montant demandé (frais inclus)."""

    def __init__(self, id_compte: str, solde: int, montant_requis: int) -> None:
        super().__init__(
            f"Solde insuffisant sur {id_compte} : {solde} GNF disponibles, "
            f"{montant_requis} GNF requis (frais inclus)"
        )
        self.id_compte = id_compte
        self.solde = solde
        self.montant_requis = montant_requis


class PlafondDepasse(PayGuardError):
    """L'opération dépasse un plafond (par opération, journalier ou de solde)."""

    def __init__(self, id_compte: str, nature: str, plafond: int, montant: int) -> None:
        super().__init__(
            f"Plafond {nature} dépassé sur {id_compte} : {montant} GNF "
            f"pour un plafond de {plafond} GNF"
        )
        self.id_compte = id_compte
        self.nature = nature
        self.plafond = plafond
        self.montant = montant


class CompteGele(PayGuardError):
    """Le compte est gelé : aucune opération ne peut le débiter ni le créditer."""

    def __init__(self, id_compte: str) -> None:
        super().__init__(f"Le compte {id_compte} est gelé")
        self.id_compte = id_compte
