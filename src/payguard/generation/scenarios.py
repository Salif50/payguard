"""Scénarios de fraude injectés dans les données synthétiques (phase 1).

Chaque scénario est une fonction pure (à graine fixée) de signature ::

    scenario(rng, victime, instant, contexte) -> list[dict]

* ``victime`` : description du compte particulier ciblé ;
* ``instant`` : moment de l'attaque, déjà tiré par l'appelant ;
* ``contexte`` : informations globales (agents par zone, comptes « mules »...).

La fonction renvoie une ou plusieurs opérations. Les opérations frauduleuses
portent ``est_fraude = 1`` ; certaines opérations légitimes peuvent les
accompagner (par exemple l'opération du vrai titulaire qui précède un
changement brutal de zone).

Pour éviter des fraudes « trop faciles », chaque scénario ne porte qu'une
partie des signaux possibles et avec une probabilité : un vol de compte
n'utilise pas toujours un nouvel appareil, une rafale n'a pas toujours lieu
la nuit, etc. À l'inverse, le générateur introduit du bruit légitime
(couche-tard, voyages, changements de téléphone, gros achats).

Le registre :data:`SCENARIOS` associe un nom à chaque fonction : ajouter un
scénario revient à écrire une fonction et à l'enregistrer, sans toucher au
générateur.
"""

from __future__ import annotations

import random
from collections.abc import Callable
from datetime import datetime, timedelta
from typing import Any

from payguard.generation.parametres import (
    ZONES,
    appareil_au_moment,
    arrondir_montant,
    creer_operation,
    identifiant_appareil,
    montant_habituel,
    tirer_montant,
)

Operation = dict[str, Any]
Scenario = Callable[[random.Random, dict[str, Any], datetime, dict[str, Any]], list[Operation]]


def _agent_de_zone(rng: random.Random, contexte: dict[str, Any], zone: str) -> str:
    """Choisit un agent de la zone (ou de n'importe quelle zone à défaut)."""
    agents = contexte["agents_par_zone"].get(zone) or contexte["tous_agents"]
    return rng.choice(agents)


def _mule(rng: random.Random, contexte: dict[str, Any]) -> str:
    """Choisit un compte « mule » contrôlé par le fraudeur pour recevoir les fonds."""
    return rng.choice(contexte["mules"])["id"]


def _zone_lointaine(rng: random.Random, victime: dict[str, Any]) -> str:
    """Choisit une zone différente des zones habituelles de la victime."""
    exclues = {victime["zone"], victime["zone_secondaire"]}
    return rng.choice([z for z in ZONES if z not in exclues])


def scenario_montant_eleve(
    rng: random.Random, victime: dict[str, Any], instant: datetime, contexte: dict[str, Any]
) -> list[Operation]:
    """Montant très supérieur aux habitudes du compte (prise de contrôle du compte)."""
    montant = arrondir_montant(montant_habituel(victime) * rng.uniform(6.0, 20.0))
    appareil = (
        appareil_au_moment(rng, victime, instant)
        if rng.random() < 0.6
        else identifiant_appareil(rng)
    )
    if rng.random() < 0.7:
        type_op, destinataire = "transfert", _mule(rng, contexte)
    else:
        type_op, destinataire = "retrait", _agent_de_zone(rng, contexte, victime["zone"])
    return [
        creer_operation(
            instant,
            victime["id"],
            destinataire,
            type_op,
            montant,
            victime["zone"],
            appareil,
            1,
            "montant_eleve",
        )
    ]


def scenario_rafale(
    rng: random.Random, victime: dict[str, Any], instant: datetime, contexte: dict[str, Any]
) -> list[Operation]:
    """Rafale de 3 à 6 transferts en quelques minutes vers des comptes différents."""
    appareil = (
        appareil_au_moment(rng, victime, instant)
        if rng.random() < 0.7
        else identifiant_appareil(rng)
    )
    operations: list[Operation] = []
    moment = instant
    for _ in range(rng.randint(3, 6)):
        montant = arrondir_montant(montant_habituel(victime) * rng.uniform(0.8, 3.0))
        operations.append(
            creer_operation(
                moment,
                victime["id"],
                _mule(rng, contexte),
                "transfert",
                montant,
                victime["zone"],
                appareil,
                1,
                "rafale",
            )
        )
        moment += timedelta(seconds=rng.randint(20, 150))
    return operations


def scenario_horaire_inhabituel(
    rng: random.Random, victime: dict[str, Any], instant: datetime, contexte: dict[str, Any]
) -> list[Operation]:
    """Une ou deux opérations en pleine nuit (0 h - 4 h 59), hors des habitudes."""
    debut = instant.replace(hour=rng.randint(0, 4), minute=rng.randrange(60))
    appareil = (
        identifiant_appareil(rng)
        if rng.random() < 0.3
        else appareil_au_moment(rng, victime, instant)
    )
    operations: list[Operation] = []
    for indice in range(rng.randint(1, 2)):
        type_op = rng.choice(("transfert", "retrait", "paiement_marchand"))
        if type_op == "transfert":
            destinataire = _mule(rng, contexte)
        elif type_op == "retrait":
            destinataire = _agent_de_zone(rng, contexte, victime["zone"])
        else:
            marchands = (
                contexte["marchands_par_zone"].get(victime["zone"]) or contexte["tous_marchands"]
            )
            destinataire = rng.choice(marchands)
        montant = arrondir_montant(montant_habituel(victime) * rng.uniform(1.5, 6.0))
        moment = debut + timedelta(minutes=indice * rng.randint(3, 25))
        operations.append(
            creer_operation(
                moment,
                victime["id"],
                destinataire,
                type_op,
                montant,
                victime["zone"],
                appareil,
                1,
                "horaire_inhabituel",
            )
        )
    return operations


def scenario_changement_zone(
    rng: random.Random, victime: dict[str, Any], instant: datetime, contexte: dict[str, Any]
) -> list[Operation]:
    """Opération légitime dans la zone habituelle puis retrait frauduleux loin, peu après.

    Le délai (15 min à 2 h 30) est incompatible avec un déplacement réel entre
    deux régions de Guinée : c'est le signal d'un « voyage impossible »
    (carte SIM clonée ou identifiants volés).
    """
    marchands = contexte["marchands_par_zone"].get(victime["zone"]) or contexte["tous_marchands"]
    legitime = creer_operation(
        instant,
        victime["id"],
        rng.choice(marchands),
        "paiement_marchand",
        tirer_montant(rng, "paiement_marchand", victime["echelle"]),
        victime["zone"],
        appareil_au_moment(rng, victime, instant),
        0,
        "",
    )
    zone = _zone_lointaine(rng, victime)
    moment = instant + timedelta(minutes=rng.randint(15, 150))
    appareil = (
        appareil_au_moment(rng, victime, moment)
        if rng.random() < 0.6
        else identifiant_appareil(rng)
    )
    fraude = creer_operation(
        moment,
        victime["id"],
        _agent_de_zone(rng, contexte, zone),
        "retrait",
        arrondir_montant(montant_habituel(victime) * rng.uniform(2.0, 8.0)),
        zone,
        appareil,
        1,
        "changement_zone",
    )
    return [legitime, fraude]


def scenario_compte_neuf_vide(
    rng: random.Random, victime: dict[str, Any], instant: datetime, contexte: dict[str, Any]
) -> list[Operation]:
    """Un compte tout juste créé reçoit des fonds détournés et se vide aussitôt.

    La victime transfère (sous la contrainte ou par usurpation) une somme
    vers une mule récemment ouverte ; la mule la retire ou la transfère
    presque entièrement dans l'heure qui suit. Toutes ces opérations sont
    frauduleuses. Si aucune mule récente n'est disponible, une mule
    quelconque est utilisée.
    """
    candidates = [
        m
        for m in contexte["mules"]
        if timedelta(0) <= instant - m["date_creation"] <= timedelta(days=5)
    ]
    mule = rng.choice(candidates) if candidates else rng.choice(contexte["mules"])
    montant = arrondir_montant(montant_habituel(victime) * rng.uniform(4.0, 15.0))
    entree = creer_operation(
        instant,
        victime["id"],
        mule["id"],
        "transfert",
        montant,
        victime["zone"],
        appareil_au_moment(rng, victime, instant),
        1,
        "compte_neuf_vide",
    )
    operations = [entree]
    moment = instant + timedelta(minutes=rng.randint(5, 60))
    restant = montant * rng.uniform(0.90, 0.97)
    nb_sorties = rng.randint(1, 2)
    for indice in range(nb_sorties):
        part = restant if indice == nb_sorties - 1 else restant * rng.uniform(0.4, 0.6)
        restant -= part
        if rng.random() < 0.6:
            type_op, destinataire = "retrait", _agent_de_zone(rng, contexte, mule["zone"])
        else:
            type_op, destinataire = "transfert", _mule(rng, contexte)
            if destinataire == mule["id"]:
                type_op = "retrait"
                destinataire = _agent_de_zone(rng, contexte, mule["zone"])
        operations.append(
            creer_operation(
                moment,
                mule["id"],
                destinataire,
                type_op,
                arrondir_montant(part),
                mule["zone"],
                mule["appareils"][0],
                1,
                "compte_neuf_vide",
            )
        )
        moment += timedelta(minutes=rng.randint(2, 30))
    return operations


def scenario_nouvel_appareil(
    rng: random.Random, victime: dict[str, Any], instant: datetime, contexte: dict[str, Any]
) -> list[Operation]:
    """Opération depuis un appareil jamais vu pour ce compte, montant élevé."""
    zone = victime["zone"] if rng.random() < 0.7 else _zone_lointaine(rng, victime)
    type_op = rng.choice(("transfert", "transfert", "retrait", "paiement_marchand"))
    if type_op == "transfert":
        destinataire = _mule(rng, contexte)
    elif type_op == "retrait":
        destinataire = _agent_de_zone(rng, contexte, zone)
    else:
        marchands = contexte["marchands_par_zone"].get(zone) or contexte["tous_marchands"]
        destinataire = rng.choice(marchands)
    montant = arrondir_montant(montant_habituel(victime) * rng.uniform(2.0, 10.0))
    return [
        creer_operation(
            instant,
            victime["id"],
            destinataire,
            type_op,
            montant,
            zone,
            identifiant_appareil(rng),
            1,
            "nouvel_appareil",
        )
    ]


#: Registre des scénarios disponibles (nom -> fonction).
SCENARIOS: dict[str, Scenario] = {
    "montant_eleve": scenario_montant_eleve,
    "rafale": scenario_rafale,
    "horaire_inhabituel": scenario_horaire_inhabituel,
    "changement_zone": scenario_changement_zone,
    "compte_neuf_vide": scenario_compte_neuf_vide,
    "nouvel_appareil": scenario_nouvel_appareil,
}
