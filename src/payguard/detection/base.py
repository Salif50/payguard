"""Classe abstraite :class:`Regle` : le contrat commun à toutes les règles de détection.

Patron *Stratégie* : le moteur ne connaît que ce contrat. Chaque règle
concrète encapsule un critère de suspicion et ses seuils ; on peut en
ajouter, en retirer ou en remplacer sans modifier le moteur.

Les sous-classes concrètes qui déclarent un attribut de classe ``nom``
s'enregistrent automatiquement (``__init_subclass__``) dans un registre :
la configuration JSON désigne une règle par ce nom. Écrire une nouvelle
classe suffit donc à la rendre configurable.
"""

from __future__ import annotations

import inspect
import math
from abc import ABC, abstractmethod
from collections.abc import Iterable
from dataclasses import dataclass
from typing import Any, ClassVar

from payguard.comptes.transaction import Transaction, TypeTransaction
from payguard.donnees.profils import ProfilCompte
from payguard.exceptions import ConfigurationInvalide, ParametreInvalide


@dataclass(frozen=True, slots=True)
class ResultatRegle:
    """Verdict d'une règle sur une transaction : déclenchée ou non, poids, motif lisible."""

    regle: str
    declenchee: bool
    poids: float = 0.0
    motif: str = ""


def valider_nombre(
    nom: str,
    valeur: Any,
    *,
    minimum: float | None = None,
    maximum: float | None = None,
    strict_minimum: bool = False,
    entier: bool = False,
) -> float:
    """Vérifie qu'un paramètre de règle est un nombre dans les
    bornes ; lève :class:`ParametreInvalide`."""
    if isinstance(valeur, bool) or not isinstance(valeur, (int, float)) or math.isnan(valeur):
        raise ParametreInvalide(f"{nom} doit être un nombre (reçu : {valeur!r})")
    if entier and not float(valeur).is_integer():
        raise ParametreInvalide(f"{nom} doit être un entier (reçu : {valeur!r})")
    if minimum is not None and (valeur <= minimum if strict_minimum else valeur < minimum):
        signe = ">" if strict_minimum else ">="
        raise ParametreInvalide(f"{nom} doit être {signe} {minimum} (reçu : {valeur!r})")
    if maximum is not None and valeur > maximum:
        raise ParametreInvalide(f"{nom} doit être <= {maximum} (reçu : {valeur!r})")
    return int(valeur) if entier else float(valeur)


def formater_gnf(montant: float) -> str:
    """``1250000`` -> ``"1 250 000 GNF"``."""
    return f"{montant:,.0f}".replace(",", " ") + " GNF"


class Regle(ABC):
    """Règle de détection : décide si une transaction est suspecte au vu du profil de l'émetteur.

    Args:
        poids: contribution de la règle au score quand elle se déclenche (>= 0).
        types_operations: types d'opérations concernés ; ``None`` = tous.

    Les sous-classes implémentent :meth:`evaluer` et appellent
    :meth:`_declencher` ou :meth:`_ignorer` pour produire leur verdict.
    """

    #: Identifiant de la règle dans la configuration (défini par chaque règle concrète).
    nom: ClassVar[str]
    #: Description courte, affichée par la CLI.
    description: ClassVar[str] = ""

    _registre: ClassVar[dict[str, type[Regle]]] = {}

    def __init_subclass__(cls, **kwargs: Any) -> None:
        super().__init_subclass__(**kwargs)
        nom = cls.__dict__.get("nom")
        if isinstance(nom, str):
            Regle._registre[nom] = cls

    def __init__(
        self,
        poids: float = 1.0,
        types_operations: Iterable[str] | None = None,
        *,
        identifiant: str | None = None,
    ) -> None:
        self._poids = valider_nombre("poids", poids, minimum=0.0)
        if identifiant is not None and (
            not isinstance(identifiant, str) or not identifiant.strip()
        ):
            raise ParametreInvalide("identifiant doit être un texte non vide")
        self._identifiant = identifiant.strip() if identifiant else type(self).nom
        if types_operations is None:
            self._types: frozenset[TypeTransaction] | None = None
        else:
            if isinstance(types_operations, str):
                raise ParametreInvalide("types_operations doit être une liste de types")
            self._types = frozenset(TypeTransaction.depuis_texte(t) for t in types_operations)
            if not self._types:
                raise ParametreInvalide("types_operations ne peut pas être vide")

    # -- contrat ---------------------------------------------------------

    @abstractmethod
    def evaluer(self, transaction: Transaction, profil: ProfilCompte) -> ResultatRegle:
        """Évalue la transaction au vu du profil de son émetteur.

        Le profil ne contient que le **passé** de la transaction (le moteur
        le met à jour après l'évaluation) ; il peut être vide pour un compte
        jamais vu. La règle ne doit jamais lire ``transaction.est_fraude``.
        """

    # -- outils pour les sous-classes ------------------------------------

    @property
    def poids(self) -> float:
        """Poids de la règle dans le score."""
        return self._poids

    @property
    def identifiant(self) -> str:
        """Nom de cette instance dans le moteur et les alertes.

        Par défaut, le ``nom`` de la classe ; un identifiant distinct permet
        d'utiliser deux fois la même stratégie avec des seuils différents
        (par exemple deux paliers de montant).
        """
        return self._identifiant

    def concerne(self, transaction: Transaction) -> bool:
        """Vrai si la règle s'applique au type de cette transaction."""
        return self._types is None or transaction.type in self._types

    def _declencher(self, motif: str) -> ResultatRegle:
        return ResultatRegle(self._identifiant, True, self._poids, motif)

    def _ignorer(self) -> ResultatRegle:
        # Le verdict négatif est immuable et toujours identique : on le réutilise.
        try:
            return self._verdict_negatif
        except AttributeError:
            self._verdict_negatif = ResultatRegle(self._identifiant, False)
            return self._verdict_negatif

    def parametres(self) -> dict[str, Any]:
        """Paramètres courants de la règle (mêmes noms que le constructeur)."""
        valeurs: dict[str, Any] = {}
        for nom in inspect.signature(type(self).__init__).parameters:
            if nom in ("self", "poids", "identifiant"):
                continue
            if nom == "types_operations":
                valeurs[nom] = (
                    None if self._types is None else sorted(t.value for t in self._types)
                )
            else:
                valeurs[nom] = getattr(self, nom)
        return valeurs

    # -- fabrique --------------------------------------------------------

    @classmethod
    def registre(cls) -> dict[str, type[Regle]]:
        """Copie du registre ``nom -> classe`` des règles disponibles."""
        return dict(Regle._registre)

    @classmethod
    def creer(
        cls, nom: str, poids: float = 1.0, identifiant: str | None = None, **parametres: Any
    ) -> Regle:
        """Instancie la règle ``nom`` avec ses paramètres.

        Raises:
            ConfigurationInvalide: règle inconnue, paramètre inconnu ou valeur invalide.
        """
        classe = Regle._registre.get(nom)
        if classe is None:
            disponibles = ", ".join(sorted(Regle._registre))
            raise ConfigurationInvalide(f"Règle inconnue : {nom!r} (disponibles : {disponibles})")
        acceptes = set(inspect.signature(classe.__init__).parameters) - {
            "self",
            "poids",
            "identifiant",
        }
        inconnus = set(parametres) - acceptes
        if inconnus:
            raise ConfigurationInvalide(
                f"Règle {nom!r} : paramètre(s) inconnu(s) {sorted(inconnus)} "
                f"(acceptés : {sorted(acceptes)})"
            )
        try:
            return classe(poids=poids, identifiant=identifiant, **parametres)
        except (ParametreInvalide, ValueError) as erreur:
            raise ConfigurationInvalide(f"Règle {identifiant or nom!r} : {erreur}") from erreur

    def __repr__(self) -> str:
        options = ", ".join(f"{k}={v!r}" for k, v in self.parametres().items())
        alias = f", identifiant={self._identifiant!r}" if self._identifiant != self.nom else ""
        suite = f", {options}" if options else ""
        return f"{type(self).__name__}(poids={self._poids:g}{alias}{suite})"
