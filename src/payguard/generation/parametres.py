"""Constantes et fonctions utilitaires partagées par le générateur et les scénarios.

Phase 1 : uniquement la bibliothèque standard (``random``, ``datetime``,
``math``). Toutes les fonctions aléatoires reçoivent explicitement un
générateur ``random.Random`` : aucune ne touche à l'état global du module
``random``, ce qui garantit la reproductibilité à graine fixée.
"""

from __future__ import annotations

import math
import random
from datetime import datetime, timedelta
from typing import Any

#: Régions administratives de Guinée et poids approximatif de leur population.
ZONES: dict[str, float] = {
    "Conakry": 0.30,
    "Kindia": 0.13,
    "Boké": 0.09,
    "Labé": 0.09,
    "Mamou": 0.07,
    "Kankan": 0.15,
    "Faranah": 0.07,
    "Nzérékoré": 0.10,
}

#: Montant médian (GNF) et dispersion log-normale (sigma) par type d'opération.
MONTANTS: dict[str, tuple[float, float]] = {
    "depot": (250_000.0, 0.9),
    "retrait": (200_000.0, 0.9),
    "transfert": (120_000.0, 1.0),
    "paiement_marchand": (45_000.0, 0.8),
}

#: Répartition des opérations initiées par un client particulier.
MELANGE_PERSONNEL: dict[str, float] = {
    "depot": 0.22,
    "retrait": 0.20,
    "transfert": 0.33,
    "paiement_marchand": 0.25,
}

#: Répartition des opérations initiées par un commerçant.
MELANGE_MARCHAND: dict[str, float] = {"retrait": 0.6, "transfert": 0.4}

#: Bornes des montants générés (GNF). Le maximum reste sous les plafonds des comptes.
MONTANT_MIN = 1_000
MONTANT_MAX = 5_000_000
PAS_ARRONDI = 500

#: Marge appliquée aux débits pour couvrir les frais (au plus 1,5 % côté comptes).
MARGE_FRAIS = 0.03

#: Prénoms et noms de famille courants en Guinée (données fictives).
PRENOMS: tuple[str, ...] = (
    "Mamadou",
    "Alpha",
    "Ibrahima",
    "Ousmane",
    "Abdoulaye",
    "Mohamed",
    "Sekou",
    "Fodé",
    "Lansana",
    "Amadou",
    "Thierno",
    "Boubacar",
    "Moussa",
    "Aboubacar",
    "Fatoumata",
    "Mariama",
    "Aïssatou",
    "Kadiatou",
    "Hawa",
    "Mariame",
    "Nènè",
    "Djénabou",
    "Oumou",
    "Adama",
    "Saran",
    "Mabinty",
    "Fanta",
    "Ramatoulaye",
)
NOMS: tuple[str, ...] = (
    "Diallo",
    "Barry",
    "Bah",
    "Sow",
    "Baldé",
    "Camara",
    "Condé",
    "Sylla",
    "Soumah",
    "Keïta",
    "Touré",
    "Kouyaté",
    "Cissé",
    "Kaba",
    "Traoré",
    "Doumbouya",
    "Konaté",
    "Bangoura",
    "Fofana",
    "Kourouma",
    "Haba",
    "Loua",
    "Guilavogui",
)


def arrondir_montant(montant: float) -> int:
    """Arrondit un montant au multiple de 500 GNF et le borne à ``[MONTANT_MIN, MONTANT_MAX]``."""
    arrondi = int(round(montant / PAS_ARRONDI)) * PAS_ARRONDI
    return max(MONTANT_MIN, min(MONTANT_MAX, arrondi))


def tirer_montant(rng: random.Random, type_operation: str, echelle: float = 1.0) -> int:
    """Tire un montant log-normal propre au type d'opération et au compte.

    Args:
        rng: générateur pseudo-aléatoire.
        type_operation: une clé de :data:`MONTANTS`.
        echelle: facteur propre au compte (un compte « aisé » a une échelle > 1).
    """
    mediane, sigma = MONTANTS[type_operation]
    return arrondir_montant(rng.lognormvariate(math.log(mediane * echelle), sigma))


def montant_habituel(compte: dict[str, Any]) -> float:
    """Montant typique d'un transfert pour ce compte (sert de référence aux fraudes)."""
    return MONTANTS["transfert"][0] * compte["echelle"]


def identifiant_appareil(rng: random.Random) -> str:
    """Produit un identifiant d'appareil pseudo-aléatoire (``APP-`` + 8 chiffres hexadécimaux)."""
    return f"APP-{rng.getrandbits(32):08X}"


def telephone_guinee(rng: random.Random) -> str:
    """Produit un numéro mobile guinéen fictif au format ``+2246XXXXXXXX``."""
    return "+2246" + "".join(str(rng.randrange(10)) for _ in range(8))


def heure_habituelle(rng: random.Random, compte: dict[str, Any]) -> int:
    """Tire une heure (0-23) autour de l'heure d'activité habituelle du compte."""
    return int(round(rng.gauss(compte["heure_centre"], compte["heure_ecart"]))) % 24


def instant_aleatoire(
    rng: random.Random,
    compte: dict[str, Any],
    debut: datetime,
    fin: datetime,
    heure: int | None = None,
) -> datetime:
    """Tire un instant entre ``debut`` et ``fin`` (exclu), à une heure plausible pour le compte."""
    nb_jours = max(1, (fin - debut).days)
    jour = debut + timedelta(days=rng.randrange(nb_jours))
    heure_tiree = heure_habituelle(rng, compte) if heure is None else heure
    return jour.replace(
        hour=heure_tiree, minute=rng.randrange(60), second=rng.randrange(60), microsecond=0
    )


def appareil_au_moment(rng: random.Random, compte: dict[str, Any], instant: datetime) -> str:
    """Appareil utilisé par le titulaire légitime à un instant donné.

    Tient compte d'un éventuel changement de téléphone légitime en cours de
    période et d'un éventuel second appareil (tablette, ancien téléphone).
    """
    changement = compte.get("date_changement_appareil")
    if changement is not None and instant >= changement:
        return compte["appareil_remplacement"]
    appareils = compte["appareils"]
    if len(appareils) > 1 and rng.random() < 0.15:
        return appareils[1]
    return appareils[0]


def zone_habituelle(rng: random.Random, compte: dict[str, Any]) -> str:
    """Zone d'une opération légitime : principale, secondaire (déplacement) ou rare."""
    tirage = rng.random()
    if tirage < 0.92:
        return compte["zone"]
    if tirage < 0.98:
        return compte["zone_secondaire"]
    return rng.choice(list(ZONES))


def creer_operation(
    horodatage: datetime,
    id_emetteur: str,
    id_destinataire: str,
    type_operation: str,
    montant: int,
    zone: str,
    appareil_id: str,
    est_fraude: int = 0,
    scenario: str = "",
) -> dict[str, Any]:
    """Construit le dictionnaire représentant une opération générée.

    La clé ``scenario`` n'est pas écrite dans le CSV de l'annexe A : elle sert
    uniquement à l'analyse a posteriori du taux de détection par scénario.
    """
    return {
        "horodatage": horodatage,
        "id_emetteur": id_emetteur,
        "id_destinataire": id_destinataire,
        "type": type_operation,
        "montant": montant,
        "zone": zone,
        "appareil_id": appareil_id,
        "est_fraude": est_fraude,
        "scenario": scenario,
    }
