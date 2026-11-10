"""Chargement et validation de la configuration JSON du moteur de règles.

Format attendu ::

    {
      "description": "texte libre (facultatif)",
      "seuil_alerte": 2.0,
      "regles": [
        {"nom": "montant_anormal", "active": true, "poids": 2.0,
         "parametres": {"facteur": 4.0, "min_operations": 3}},
        ...
      ]
    }

La validation est stricte : clé inconnue (faute de frappe), type incorrect,
poids négatif, règle inconnue, paramètre inconnu ou hors bornes, doublon
de règle, aucune règle active... lèvent :class:`ConfigurationInvalide` avec
un message qui désigne précisément l'élément fautif.
"""

from __future__ import annotations

import json
import math
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from payguard.detection.base import Regle
from payguard.detection.moteur import MoteurDeRegles
from payguard.exceptions import ConfigurationInvalide

# Importer les règles concrètes les enregistre dans le registre de Regle.
from payguard.detection import regles as _regles  # noqa: F401

_CLES_RACINE = {"description", "seuil_alerte", "regles"}
_CLES_REGLE = {"nom", "identifiant", "active", "poids", "parametres"}


@dataclass(frozen=True)
class ConfigurationRegle:
    """Configuration d'une règle : nom, activation, poids et seuils."""

    nom: str
    active: bool = True
    poids: float = 1.0
    parametres: dict[str, Any] = field(default_factory=dict)
    identifiant: str | None = None

    @property
    def cle(self) -> str:
        """Identifiant effectif de la règle (``identifiant`` s'il est donné, sinon ``nom``)."""
        return self.identifiant or self.nom

    def construire(self) -> Regle:
        """Instancie la règle (lève :class:`ConfigurationInvalide`
        si un paramètre est invalide)."""
        return Regle.creer(self.nom, self.poids, self.identifiant, **self.parametres)

    def vers_dict(self) -> dict[str, Any]:
        """Représentation JSON-sérialisable."""
        donnees: dict[str, Any] = {"nom": self.nom}
        if self.identifiant:
            donnees["identifiant"] = self.identifiant
        donnees.update(active=self.active, poids=self.poids, parametres=dict(self.parametres))
        return donnees


@dataclass(frozen=True)
class ConfigurationMoteur:
    """Configuration complète du moteur."""

    seuil_alerte: float
    regles: tuple[ConfigurationRegle, ...]
    description: str = ""

    @classmethod
    def depuis_dict(cls, donnees: Any, source: str = "configuration") -> ConfigurationMoteur:
        """Valide un dictionnaire (issu du JSON) et construit la configuration.

        Toutes les règles sont instanciées une fois pour valider leurs
        paramètres : une configuration acceptée est forcément utilisable.
        """
        if not isinstance(donnees, dict):
            raise ConfigurationInvalide(f"{source} : la racine doit être un objet JSON")
        inconnues = set(donnees) - _CLES_RACINE
        if inconnues:
            raise ConfigurationInvalide(f"{source} : clé(s) inconnue(s) {sorted(inconnues)}")
        if "seuil_alerte" not in donnees:
            raise ConfigurationInvalide(f"{source} : 'seuil_alerte' est obligatoire")
        seuil = donnees["seuil_alerte"]
        if (
            isinstance(seuil, bool)
            or not isinstance(seuil, (int, float))
            or not math.isfinite(seuil)
            or seuil <= 0
        ):
            raise ConfigurationInvalide(
                f"{source} : 'seuil_alerte' doit être un nombre > 0 (reçu : {seuil!r})"
            )
        description = donnees.get("description", "")
        if not isinstance(description, str):
            raise ConfigurationInvalide(f"{source} : 'description' doit être un texte")
        liste = donnees.get("regles")
        if not isinstance(liste, list) or not liste:
            raise ConfigurationInvalide(f"{source} : 'regles' doit être une liste non vide")

        regles: list[ConfigurationRegle] = []
        vus: set[str] = set()
        for position, element in enumerate(liste, start=1):
            regle = cls._valider_regle(element, f"{source}, règle n° {position}")
            if regle.cle in vus:
                raise ConfigurationInvalide(
                    f"{source} : la règle {regle.cle!r} apparaît deux fois "
                    "(donnez un 'identifiant' distinct pour réutiliser une règle)"
                )
            vus.add(regle.cle)
            regle.construire()  # valide les paramètres
            regles.append(regle)
        if not any(r.active for r in regles):
            raise ConfigurationInvalide(f"{source} : aucune règle active")
        return cls(float(seuil), tuple(regles), description)

    @staticmethod
    def _valider_regle(element: Any, contexte: str) -> ConfigurationRegle:
        if not isinstance(element, dict):
            raise ConfigurationInvalide(f"{contexte} : chaque règle doit être un objet JSON")
        inconnues = set(element) - _CLES_REGLE
        if inconnues:
            raise ConfigurationInvalide(f"{contexte} : clé(s) inconnue(s) {sorted(inconnues)}")
        nom = element.get("nom")
        if not isinstance(nom, str) or not nom:
            raise ConfigurationInvalide(
                f"{contexte} : 'nom' est obligatoire et doit être un texte"
            )
        if nom not in Regle.registre():
            raise ConfigurationInvalide(
                f"{contexte} : règle inconnue {nom!r} (disponibles "
                f": {', '.join(sorted(Regle.registre()))})"
            )
        active = element.get("active", True)
        if not isinstance(active, bool):
            raise ConfigurationInvalide(f"{contexte} ({nom}) : 'active' doit être true ou false")
        poids = element.get("poids", 1.0)
        if (
            isinstance(poids, bool)
            or not isinstance(poids, (int, float))
            or not math.isfinite(poids)
            or poids < 0
        ):
            raise ConfigurationInvalide(
                f"{contexte} ({nom}) : 'poids' doit être un nombre >= 0 (reçu : {poids!r})"
            )
        parametres = element.get("parametres", {})
        if not isinstance(parametres, dict):
            raise ConfigurationInvalide(
                f"{contexte} ({nom}) : 'parametres' doit être un objet JSON"
            )
        identifiant = element.get("identifiant")
        if identifiant is not None and (
            not isinstance(identifiant, str) or not identifiant.strip()
        ):
            raise ConfigurationInvalide(
                f"{contexte} ({nom}) : 'identifiant' doit être un texte non vide"
            )
        return ConfigurationRegle(nom, active, float(poids), dict(parametres), identifiant)

    def construire_moteur(self) -> MoteurDeRegles:
        """Moteur prêt à l'emploi avec les règles actives."""
        return MoteurDeRegles(
            (r.construire() for r in self.regles if r.active), seuil_alerte=self.seuil_alerte
        )

    def avec(self, **modifications: Any) -> ConfigurationMoteur:
        """Copie modifiée : ``seuil_alerte=...`` et/ou ``<regle>__poids``,
        ``<regle>__active``, ``<regle>__<parametre>`` (utile pour comparer des réglages).

        ``<regle>`` désigne l'identifiant effectif de la règle."""
        seuil = modifications.pop("seuil_alerte", self.seuil_alerte)
        regles = []
        for regle in self.regles:
            active, poids, parametres = regle.active, regle.poids, dict(regle.parametres)
            for cle, valeur in list(modifications.items()):
                nom, _, champ = cle.partition("__")
                if nom != regle.cle:
                    continue
                modifications.pop(cle)
                if champ == "active":
                    active = valeur
                elif champ == "poids":
                    poids = valeur
                else:
                    parametres[champ] = valeur
            regles.append(
                ConfigurationRegle(regle.nom, active, poids, parametres, regle.identifiant)
            )
        if modifications:
            raise ConfigurationInvalide(
                f"Modifications sans règle correspondante : {sorted(modifications)}"
            )
        return ConfigurationMoteur.depuis_dict(
            {
                "description": self.description,
                "seuil_alerte": seuil,
                "regles": [r.vers_dict() for r in regles],
            },
            source="configuration modifiée",
        )

    def vers_dict(self) -> dict[str, Any]:
        """Représentation JSON-sérialisable."""
        return {
            "description": self.description,
            "seuil_alerte": self.seuil_alerte,
            "regles": [r.vers_dict() for r in self.regles],
        }


def charger_configuration(chemin: str | Path) -> ConfigurationMoteur:
    """Lit et valide un fichier de configuration JSON.

    Raises:
        ConfigurationInvalide: fichier absent, JSON mal formé ou contenu invalide.
    """
    chemin = Path(chemin)
    if not chemin.is_file():
        raise ConfigurationInvalide(f"Fichier de configuration introuvable : {chemin}")
    try:
        donnees = json.loads(chemin.read_text(encoding="utf-8"))
    except json.JSONDecodeError as erreur:
        raise ConfigurationInvalide(
            f"{chemin.name} : JSON invalide ligne {erreur.lineno}, "
            f"colonne {erreur.colno} ({erreur.msg})"
        ) from erreur
    except (OSError, UnicodeDecodeError) as erreur:
        raise ConfigurationInvalide(f"Lecture impossible de {chemin} : {erreur}") from erreur
    return ConfigurationMoteur.depuis_dict(donnees, source=chemin.name)


def enregistrer_configuration(configuration: ConfigurationMoteur, chemin: str | Path) -> Path:
    """Écrit la configuration en JSON indenté (UTF-8)."""
    chemin = Path(chemin)
    chemin.parent.mkdir(parents=True, exist_ok=True)
    chemin.write_text(
        json.dumps(configuration.vers_dict(), indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    return chemin


#: Configuration intégrée au paquet, utilisée si aucun fichier n'est fourni.
#: Elle est identique à ``config/regles.json`` (réglage retenu, voir le rapport).
CONFIGURATION_PAR_DEFAUT: dict[str, Any] = {
    "description": (
        "Réglage retenu (coût métier minimal) : toute sortie d'argent >= 150 000 GNF est "
        "signalée, entre 50 000 et 150 000 GNF il faut un indice, rafale et nouvel appareil "
        "suffisent seuls."
    ),
    "seuil_alerte": 2.0,
    "regles": [
        {
            "nom": "montant_anormal",
            "poids": 1.0,
            "parametres": {"facteur": 4.0, "min_operations": 3, "montant_minimum": 100000},
        },
        {"nom": "rafale", "poids": 2.0, "parametres": {"nb_operations": 2, "fenetre_minutes": 5}},
        {
            "nom": "horaire_inhabituel",
            "poids": 1.0,
            "parametres": {"heure_debut": 0, "heure_fin": 5, "part_max": 0.1},
        },
        {
            "nom": "changement_zone",
            "poids": 1.0,
            "parametres": {"delai_minutes": 180, "min_operations": 5, "part_min": 0.0},
        },
        {"nom": "nouvel_appareil", "poids": 2.0, "parametres": {"min_operations": 2}},
        {
            "nom": "compte_recent_vide",
            "poids": 1.0,
            "parametres": {"anciennete_max_jours": 7, "part_min": 0.8, "montant_minimum": 50000},
        },
        {
            "nom": "montant_eleve",
            "identifiant": "montant_significatif",
            "poids": 1.0,
            "parametres": {
                "seuil": 50000,
                "types_operations": ["retrait", "transfert", "paiement_marchand"],
            },
        },
        {
            "nom": "montant_eleve",
            "poids": 1.0,
            "parametres": {
                "seuil": 150000,
                "types_operations": ["retrait", "transfert", "paiement_marchand"],
            },
        },
    ],
}


def configuration_par_defaut() -> ConfigurationMoteur:
    """Configuration intégrée, validée."""
    return ConfigurationMoteur.depuis_dict(
        CONFIGURATION_PAR_DEFAUT, source="configuration par défaut"
    )
