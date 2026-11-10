"""Phase 1 — générateur de transactions synthétiques.

Écrit sous forme de fonctions, avec les seuls modules ``random``, ``csv``,
``datetime`` et ``math`` de la bibliothèque standard. Le déroulement est :

1. :func:`generer_comptes` — population de comptes (particuliers, marchands,
   agents) avec leurs habitudes : zone, appareils, heures, échelle de montants ;
2. :func:`generer_operations_normales` — opérations légitimes ;
3. :func:`equilibrer_soldes` — ajoute les dépôts de réapprovisionnement pour
   qu'aucun compte ne dépense plus que son solde (les données doivent pouvoir
   passer par les règles métier de la phase 2) ;
4. :func:`injecter_fraudes` — scénarios de fraude (voir :mod:`.scenarios`) ;
5. :func:`attribuer_identifiants` puis :func:`ecrire_csv` — fichier de l'annexe A.

Toute l'aléa provient d'une unique instance ``random.Random(graine)`` : deux
appels avec les mêmes paramètres produisent un fichier identique octet pour octet.
"""

from __future__ import annotations

import csv
import logging
import math
import random
from collections import Counter
from datetime import date, datetime, time, timedelta
from pathlib import Path
from typing import Any, Iterable

from payguard.exceptions import ParametreInvalide
from payguard.generation.parametres import (
    MARGE_FRAIS,
    MELANGE_MARCHAND,
    MELANGE_PERSONNEL,
    NOMS,
    PAS_ARRONDI,
    PRENOMS,
    ZONES,
    appareil_au_moment,
    creer_operation,
    identifiant_appareil,
    instant_aleatoire,
    telephone_guinee,
    tirer_montant,
    zone_habituelle,
)
from payguard.generation.scenarios import SCENARIOS
from payguard.schema import COLONNES

journal = logging.getLogger(__name__)

Compte = dict[str, Any]
Operation = dict[str, Any]

#: Valeurs par défaut documentées (reprises par la CLI).
NB_COMPTES_DEFAUT = 5_000
NB_OPERATIONS_DEFAUT = 110_000
DEBUT_DEFAUT = date(2026, 1, 1)
FIN_DEFAUT = date(2026, 7, 1)
TAUX_FRAUDE_DEFAUT = 0.015
GRAINE_DEFAUT = 42

PART_AGENTS = 0.03
PART_MARCHANDS = 0.10
PART_MULES = 0.03
SOLDE_INITIAL_AGENT = 5_000_000_000
PLAFOND_DEPOT_REAPPRO = 9_500_000
MONTANT_FRAUDE_MIN = 5_000
#: Part des opérations légitimes non provisionnées laissées telles quelles (rejetées en phase 2).
PART_TENTATIVES_SANS_SOLDE = 0.02


# --------------------------------------------------------------------------
# Validation
# --------------------------------------------------------------------------


def _est_entier(valeur: Any) -> bool:
    return isinstance(valeur, int) and not isinstance(valeur, bool)


def valider_parametres(
    nb_comptes: int,
    nb_operations: int,
    debut: date,
    fin: date,
    taux_fraude: float,
    graine: int,
) -> None:
    """Vérifie les paramètres du générateur et lève :class:`ParametreInvalide` sinon.

    Règles : au moins 50 comptes (il faut des agents et des marchands dans
    chaque zone), au moins 100 opérations, une période d'au moins 30 jours
    (les victimes doivent avoir un historique avant d'être attaquées), un
    taux de fraude dans ``[0 ; 0,2]`` et une graine entière.
    """
    if not _est_entier(nb_comptes) or not 50 <= nb_comptes <= 500_000:
        raise ParametreInvalide(
            f"nb_comptes doit être un entier entre 50 et 500 000 (reçu : {nb_comptes!r})"
        )
    if not _est_entier(nb_operations) or not 100 <= nb_operations <= 10_000_000:
        raise ParametreInvalide(
            f"nb_operations doit être un entier entre 100 et 10 000 000 (reçu : {nb_operations!r})"
        )
    for nom, valeur in (("debut", debut), ("fin", fin)):
        if not isinstance(valeur, date):
            raise ParametreInvalide(f"{nom} doit être une date (reçu : {valeur!r})")
    if (fin - debut).days < 30:
        raise ParametreInvalide(f"La période doit couvrir au moins 30 jours (du {debut} au {fin})")
    if (
        not isinstance(taux_fraude, (int, float))
        or isinstance(taux_fraude, bool)
        or math.isnan(taux_fraude)
        or not 0.0 <= taux_fraude <= 0.2
    ):
        raise ParametreInvalide(
            f"taux_fraude doit être un nombre entre 0 et 0,2 (reçu : {taux_fraude!r})"
        )
    if not _est_entier(graine):
        raise ParametreInvalide(f"graine doit être un entier (reçu : {graine!r})")


def _vers_datetime(jour: date) -> datetime:
    """Convertit une date (ou un datetime) en datetime à minuit."""
    if isinstance(jour, datetime):
        return jour.replace(hour=0, minute=0, second=0, microsecond=0)
    return datetime.combine(jour, time())


# --------------------------------------------------------------------------
# Comptes
# --------------------------------------------------------------------------


def _arrondir_solde(valeur: float) -> int:
    return int(round(valeur / PAS_ARRONDI)) * PAS_ARRONDI


def _nouveau_compte(
    rng: random.Random,
    id_compte: str,
    type_compte: str,
    zone: str,
    date_creation: datetime,
    debut: datetime,
    fin: datetime,
) -> Compte:
    """Construit la description d'un compte et de son titulaire."""
    autres_zones = [z for z in ZONES if z != zone]
    appareils = [identifiant_appareil(rng)]
    if rng.random() < 0.12:
        appareils.append(identifiant_appareil(rng))

    compte: Compte = {
        "id": id_compte,
        "type": type_compte,
        "zone": zone,
        "zone_secondaire": rng.choice(autres_zones),
        "appareils": appareils,
        "date_changement_appareil": None,
        "appareil_remplacement": None,
        "date_creation": date_creation,
        "echelle": rng.lognormvariate(0.0, 0.5),
        "activite": rng.lognormvariate(0.0, 1.0),
        "heure_centre": rng.uniform(9.0, 19.0),
        "heure_ecart": rng.uniform(2.0, 3.5),
        "est_mule": False,
        "contacts": [],
        "id_client": "CL" + id_compte[1:],
        "nom": f"{rng.choice(PRENOMS)} {rng.choice(NOMS)}",
        "telephone": telephone_guinee(rng),
        "solde_initial": 0,
    }
    # Bruit légitime : couche-tard et changement de téléphone en cours de période.
    if type_compte == "personnel" and rng.random() < 0.04:
        compte["heure_centre"] = rng.uniform(21.5, 23.5)
        compte["heure_ecart"] = 2.5
    if type_compte == "personnel" and rng.random() < 0.06:
        debut_possible = max(debut, date_creation)
        delta = max(1, int((fin - debut_possible).total_seconds()))
        compte["date_changement_appareil"] = debut_possible + timedelta(
            seconds=rng.randrange(delta)
        )
        compte["appareil_remplacement"] = identifiant_appareil(rng)
    return compte


def generer_comptes(
    nb_comptes: int, debut: datetime, fin: datetime, rng: random.Random
) -> list[Compte]:
    """Génère la population de comptes.

    Environ 3 % d'agents, 10 % de marchands et 87 % de particuliers ; chaque
    zone reçoit au moins un agent et un marchand. Un quart des particuliers
    ouvre son compte pendant la période ; parmi eux, quelques comptes
    « mules » serviront aux fraudeurs.
    """
    zones = list(ZONES)
    poids_zones = list(ZONES.values())
    nb_agents = max(len(zones), round(nb_comptes * PART_AGENTS))
    nb_marchands = max(len(zones), round(nb_comptes * PART_MARCHANDS))
    nb_personnels = nb_comptes - nb_agents - nb_marchands
    duree = fin - debut

    def zone_pour(indice: int) -> str:
        # Les premiers comptes de chaque type couvrent toutes les zones.
        return zones[indice] if indice < len(zones) else rng.choices(zones, poids_zones)[0]

    def creation_ancienne() -> datetime:
        return (debut - timedelta(days=rng.uniform(30, 900))).replace(microsecond=0)

    comptes: list[Compte] = []
    for i in range(nb_agents):
        compte = _nouveau_compte(
            rng, f"A{i + 1:06d}", "agent", zone_pour(i), creation_ancienne(), debut, fin
        )
        compte.update(heure_centre=13.0, heure_ecart=3.5, solde_initial=SOLDE_INITIAL_AGENT)
        compte["appareils"] = compte["appareils"][:1]
        comptes.append(compte)

    for i in range(nb_marchands):
        compte = _nouveau_compte(
            rng, f"M{i + 1:06d}", "marchand", zone_pour(i), creation_ancienne(), debut, fin
        )
        compte["echelle"] *= 3.0
        compte["activite"] *= 0.6
        compte.update(heure_centre=13.0, heure_ecart=3.0)
        compte["solde_initial"] = _arrondir_solde(rng.lognormvariate(math.log(2_000_000), 0.6))
        comptes.append(compte)

    personnels: list[Compte] = []
    for i in range(nb_personnels):
        recent = rng.random() < 0.25
        creation = debut + duree * rng.uniform(0.0, 0.85) if recent else creation_ancienne()
        creation = creation.replace(microsecond=0)  # le format d'échange est à la seconde
        compte = _nouveau_compte(
            rng, f"P{i + 1:06d}", "personnel", zone_pour(i), creation, debut, fin
        )
        if not recent:
            compte["solde_initial"] = _arrondir_solde(
                rng.lognormvariate(math.log(400_000 * compte["echelle"]), 0.8)
            )
        personnels.append(compte)

    # Comptes mules : ouverts pendant la période, très peu d'activité propre.
    recents = [c for c in personnels if c["date_creation"] >= debut]
    for mule in rng.sample(recents, min(len(recents), max(5, round(nb_personnels * PART_MULES)))):
        mule["est_mule"] = True
        mule["activite"] = 0.15

    # Réseau social : chaque particulier transfère surtout vers quelques proches.
    par_zone: dict[str, list[str]] = {}
    for compte in personnels:
        par_zone.setdefault(compte["zone"], []).append(compte["id"])
    tous_ids = [c["id"] for c in personnels]
    for compte in personnels:
        contacts: list[str] = []
        for _ in range(rng.randint(3, 8)):
            reservoir = par_zone[compte["zone"]] if rng.random() < 0.8 else tous_ids
            contact = rng.choice(reservoir)
            if contact != compte["id"]:
                contacts.append(contact)
        compte["contacts"] = contacts or [rng.choice([i for i in tous_ids if i != compte["id"]])]

    comptes.extend(personnels)
    journal.info(
        "Comptes générés : %d agents, %d marchands, %d particuliers",
        nb_agents,
        nb_marchands,
        nb_personnels,
    )
    return comptes


def construire_contexte(comptes: list[Compte]) -> dict[str, Any]:
    """Index utiles au générateur et aux scénarios (agents et marchands par zone, mules)."""
    contexte: dict[str, Any] = {
        "index": {c["id"]: c for c in comptes},
        "agents_par_zone": {},
        "marchands_par_zone": {},
        "tous_agents": [],
        "tous_marchands": [],
        "personnels": [],
        "mules": [],
    }
    for compte in comptes:
        if compte["type"] == "agent":
            contexte["agents_par_zone"].setdefault(compte["zone"], []).append(compte["id"])
            contexte["tous_agents"].append(compte["id"])
        elif compte["type"] == "marchand":
            contexte["marchands_par_zone"].setdefault(compte["zone"], []).append(compte["id"])
            contexte["tous_marchands"].append(compte["id"])
        else:
            contexte["personnels"].append(compte)
            if compte["est_mule"]:
                contexte["mules"].append(compte)
    return contexte


# --------------------------------------------------------------------------
# Opérations légitimes
# --------------------------------------------------------------------------


def _agent(rng: random.Random, contexte: dict[str, Any], zone: str) -> str:
    return rng.choice(contexte["agents_par_zone"].get(zone) or contexte["tous_agents"])


def _operation_normale(
    rng: random.Random, compte: Compte, debut: datetime, fin: datetime, contexte: dict[str, Any]
) -> Operation:
    """Tire une opération légitime initiée par (ou pour) le compte."""
    depart = max(debut, compte["date_creation"])
    instant = instant_aleatoire(
        rng, compte, depart.replace(hour=0, minute=0, second=0, microsecond=0), fin
    )
    if instant < compte["date_creation"]:
        instant = compte["date_creation"] + timedelta(minutes=rng.randint(1, 120))
    zone = zone_habituelle(rng, compte)
    melange = MELANGE_PERSONNEL if compte["type"] == "personnel" else MELANGE_MARCHAND
    type_op = rng.choices(list(melange), list(melange.values()))[0]
    montant = tirer_montant(rng, type_op, compte["echelle"])
    appareil = appareil_au_moment(rng, compte, instant)

    if type_op == "depot":
        agent = _agent(rng, contexte, zone)
        agent_appareil = contexte["index"][agent]["appareils"][0]
        return creer_operation(
            instant, agent, compte["id"], "depot", montant, zone, agent_appareil
        )
    if type_op == "retrait":
        destinataire = _agent(rng, contexte, zone)
    elif type_op == "transfert":
        destinataire = (
            rng.choice(compte["contacts"])
            if compte["contacts"]
            else rng.choice(contexte["personnels"])["id"]
        )
    else:
        marchands = contexte["marchands_par_zone"].get(zone) or contexte["tous_marchands"]
        destinataire = rng.choice(marchands)
    return creer_operation(instant, compte["id"], destinataire, type_op, montant, zone, appareil)


def generer_operations_normales(
    comptes: list[Compte],
    nb_operations: int,
    debut: datetime,
    fin: datetime,
    rng: random.Random,
    contexte: dict[str, Any] | None = None,
) -> list[Operation]:
    """Génère ``nb_operations`` opérations légitimes.

    Le nombre d'opérations d'un compte est proportionnel à son activité
    (loi log-normale, donc très inégale : quelques comptes très actifs) et à
    sa durée d'existence sur la période.
    """
    contexte = contexte or construire_contexte(comptes)
    acteurs = [c for c in comptes if c["type"] in ("personnel", "marchand")]
    duree = (fin - debut).total_seconds()
    poids = [
        c["activite"] * max(0.01, (fin - max(debut, c["date_creation"])).total_seconds() / duree)
        for c in acteurs
    ]
    emetteurs = rng.choices(acteurs, weights=poids, k=nb_operations)
    return [_operation_normale(rng, compte, debut, fin, contexte) for compte in emetteurs]


# --------------------------------------------------------------------------
# Cohérence des soldes
# --------------------------------------------------------------------------


def equilibrer_soldes(
    comptes: list[Compte],
    operations: Iterable[Operation],
    rng: random.Random,
    contexte: dict[str, Any] | None = None,
) -> list[Operation]:
    """Rend la séquence d'opérations compatible avec les soldes des comptes.

    Les opérations sont rejouées dans l'ordre chronologique avec un solde
    estimé (frais majorés de :data:`MARGE_FRAIS`, donc estimation prudente) :

    * une opération légitime non couverte est précédée d'un dépôt de
      réapprovisionnement chez un agent de la zone ;
    * une opération frauduleuse non couverte est plafonnée au solde
      disponible (un fraudeur ne peut vider que ce qui existe), ou
      supprimée si le reste est dérisoire.

    Returns:
        Nouvelle liste triée par horodatage.
    """
    contexte = contexte or construire_contexte(comptes)
    index = contexte["index"]
    soldes = {c["id"]: c["solde_initial"] for c in comptes}
    resultat: list[Operation] = []
    for operation in sorted(operations, key=lambda op: op["horodatage"]):
        emetteur = operation["id_emetteur"]
        if index[emetteur]["type"] != "agent":
            besoin = math.ceil(operation["montant"] * (1 + MARGE_FRAIS))
            if soldes[emetteur] < besoin:
                if operation["est_fraude"]:
                    plafond = int(soldes[emetteur] / (1 + MARGE_FRAIS) / PAS_ARRONDI) * PAS_ARRONDI
                    if plafond < MONTANT_FRAUDE_MIN:
                        continue
                    operation = {**operation, "montant": plafond}
                elif operation.get("sans_provision") or rng.random() < PART_TENTATIVES_SANS_SOLDE:
                    # Erreur du client : l'opération est tentée sans provision.
                    # Elle reste dans la séquence (et dans le CSV brut de la
                    # phase 1) mais sera rejetée par la plateforme (phase 2).
                    # Le marqueur garde cette décision lors des passes suivantes.
                    operation["sans_provision"] = True
                    resultat.append(operation)
                    continue
                else:
                    resultat.append(
                        _reapprovisionnement(
                            rng, index[emetteur], operation, besoin - soldes[emetteur], contexte
                        )
                    )
                    soldes[resultat[-1]["id_emetteur"]] -= resultat[-1]["montant"]
                    soldes[emetteur] += resultat[-1]["montant"]
            soldes[emetteur] -= math.ceil(operation["montant"] * (1 + MARGE_FRAIS))
        else:
            soldes[emetteur] -= operation["montant"]
        soldes[operation["id_destinataire"]] += operation["montant"]
        resultat.append(operation)
    resultat.sort(key=lambda op: op["horodatage"])
    return resultat


def _reapprovisionnement(
    rng: random.Random, compte: Compte, operation: Operation, manque: int, contexte: dict[str, Any]
) -> Operation:
    """Dépôt légitime effectué peu avant une opération que le solde ne couvrirait pas."""
    montant = manque + tirer_montant(rng, "depot", compte["echelle"])
    montant = min(PLAFOND_DEPOT_REAPPRO, math.ceil(montant / PAS_ARRONDI) * PAS_ARRONDI)
    moment = operation["horodatage"] - timedelta(minutes=rng.randint(2, 90))
    if moment < compte["date_creation"]:
        moment = operation["horodatage"]
    agent = _agent(rng, contexte, operation["zone"])
    return creer_operation(
        moment,
        agent,
        compte["id"],
        "depot",
        montant,
        operation["zone"],
        contexte["index"][agent]["appareils"][0],
    )


# --------------------------------------------------------------------------
# Fraudes
# --------------------------------------------------------------------------


def injecter_fraudes(
    comptes: list[Compte],
    nb_fraudes: int,
    debut: datetime,
    fin: datetime,
    rng: random.Random,
    contexte: dict[str, Any] | None = None,
) -> list[Operation]:
    """Génère des scénarios de fraude jusqu'à obtenir au moins
    ``nb_fraudes`` opérations frauduleuses.

    Le scénario est tiré uniformément dans :data:`~payguard.generation.scenarios.SCENARIOS` ;
    la victime est un particulier (hors mules) qui possède au moins quinze
    jours d'historique au moment de l'attaque.
    """
    contexte = contexte or construire_contexte(comptes)
    if nb_fraudes <= 0:
        return []
    victimes = [
        c
        for c in contexte["personnels"]
        if not c["est_mule"] and c["date_creation"] <= fin - timedelta(days=20)
    ]
    if not victimes or not contexte["mules"]:
        raise ParametreInvalide("Population trop petite pour injecter des fraudes")
    noms = sorted(SCENARIOS)
    operations: list[Operation] = []
    nb_frauduleuses = 0
    while nb_frauduleuses < nb_fraudes:
        nom = rng.choice(noms)
        victime = rng.choice(victimes)
        depart = max(debut, victime["date_creation"] + timedelta(days=15))
        depart = depart.replace(hour=0, minute=0, second=0, microsecond=0)
        instant = instant_aleatoire(rng, victime, depart, fin)
        nouvelles = SCENARIOS[nom](rng, victime, instant, contexte)
        operations.extend(nouvelles)
        nb_frauduleuses += sum(op["est_fraude"] for op in nouvelles)
    return operations


# --------------------------------------------------------------------------
# Assemblage et écriture
# --------------------------------------------------------------------------


def attribuer_identifiants(operations: list[Operation]) -> list[Operation]:
    """Trie les opérations par horodatage et leur attribue ``TX00000001``, ``TX00000002``..."""
    operations.sort(key=lambda op: op["horodatage"])
    for rang, operation in enumerate(operations, start=1):
        operation["id_transaction"] = f"TX{rang:08d}"
    return operations


def generer_transactions(
    nb_comptes: int = NB_COMPTES_DEFAUT,
    nb_operations: int = NB_OPERATIONS_DEFAUT,
    debut: date = DEBUT_DEFAUT,
    fin: date = FIN_DEFAUT,
    taux_fraude: float = TAUX_FRAUDE_DEFAUT,
    graine: int = GRAINE_DEFAUT,
) -> tuple[list[Compte], list[Operation]]:
    """Génère les comptes et l'ensemble des opérations (légitimes et frauduleuses).

    Args:
        nb_comptes: nombre total de comptes (agents, marchands, particuliers).
        nb_operations: nombre d'opérations légitimes tirées ; le fichier final
            contient en plus les dépôts de réapprovisionnement et les fraudes.
        debut: premier jour de la période (inclus).
        fin: dernier jour de la période (exclu).
        taux_fraude: part visée d'opérations frauduleuses dans le fichier final.
        graine: graine du générateur pseudo-aléatoire.

    Returns:
        Le couple ``(comptes, operations)`` ; les opérations sont triées et identifiées.

    Raises:
        ParametreInvalide: si un paramètre est invalide.
    """
    valider_parametres(nb_comptes, nb_operations, debut, fin, taux_fraude, graine)
    rng = random.Random(graine)
    debut_dt, fin_dt = _vers_datetime(debut), _vers_datetime(fin)

    comptes = generer_comptes(nb_comptes, debut_dt, fin_dt, rng)
    contexte = construire_contexte(comptes)
    operations = generer_operations_normales(
        comptes, nb_operations, debut_dt, fin_dt, rng, contexte
    )
    operations = equilibrer_soldes(comptes, operations, rng, contexte)

    # Les fraudes peuvent être plafonnées ou supprimées par l'équilibrage :
    # on complète en quelques passes pour approcher le taux visé.
    cible = round(taux_fraude * len(operations) / (1 - taux_fraude)) if taux_fraude else 0
    for _ in range(4):
        actuelles = sum(op["est_fraude"] for op in operations)
        manquantes = cible - actuelles
        if manquantes <= max(1, cible // 100):
            break
        nouvelles = injecter_fraudes(comptes, manquantes, debut_dt, fin_dt, rng, contexte)
        operations = equilibrer_soldes(comptes, operations + nouvelles, rng, contexte)

    attribuer_identifiants(operations)
    journal.info(
        "Génération terminée : %d opérations dont %d frauduleuses (graine %d)",
        len(operations),
        sum(op["est_fraude"] for op in operations),
        graine,
    )
    return comptes, operations


def ecrire_csv(operations: Iterable[Operation], chemin: str | Path) -> int:
    """Écrit les opérations au format de l'annexe A (UTF-8, virgule, en-tête).

    Returns:
        Le nombre de lignes de données écrites.
    """
    chemin = Path(chemin)
    chemin.parent.mkdir(parents=True, exist_ok=True)
    nb_lignes = 0
    with chemin.open("w", newline="", encoding="utf-8") as fichier:
        ecrivain = csv.DictWriter(fichier, fieldnames=COLONNES, extrasaction="ignore")
        ecrivain.writeheader()
        for operation in operations:
            ligne = dict(operation)
            horodatage = ligne["horodatage"]
            if isinstance(horodatage, datetime):
                ligne["horodatage"] = horodatage.isoformat(timespec="seconds")
            ecrivain.writerow(ligne)
            nb_lignes += 1
    journal.info("%d transactions écrites dans %s", nb_lignes, chemin)
    return nb_lignes


def ecrire_scenarios(operations: Iterable[Operation], chemin: str | Path) -> int:
    """Écrit le fichier annexe ``id_transaction,scenario`` des opérations frauduleuses.

    Ce fichier ne fait pas partie du format d'échange : il sert à mesurer le
    taux de détection par scénario lors de l'évaluation.
    """
    chemin = Path(chemin)
    chemin.parent.mkdir(parents=True, exist_ok=True)
    nb_lignes = 0
    with chemin.open("w", newline="", encoding="utf-8") as fichier:
        ecrivain = csv.writer(fichier)
        ecrivain.writerow(["id_transaction", "scenario"])
        for operation in operations:
            if operation["est_fraude"]:
                ecrivain.writerow([operation["id_transaction"], operation["scenario"]])
                nb_lignes += 1
    return nb_lignes


def statistiques(operations: list[Operation]) -> dict[str, Any]:
    """Résumé d'un jeu d'opérations : volumes, taux de fraude, répartition par type et scénario."""
    nb = len(operations)
    nb_fraudes = sum(op["est_fraude"] for op in operations)
    return {
        "nb_transactions": nb,
        "nb_fraudes": nb_fraudes,
        "taux_fraude": nb_fraudes / nb if nb else 0.0,
        "nb_comptes_actifs": len(
            {op["id_emetteur"] for op in operations} | {op["id_destinataire"] for op in operations}
        ),
        "par_type": dict(Counter(op["type"] for op in operations)),
        "par_scenario": dict(Counter(op["scenario"] for op in operations if op["est_fraude"])),
        "debut": min(op["horodatage"] for op in operations).isoformat() if nb else None,
        "fin": max(op["horodatage"] for op in operations).isoformat() if nb else None,
    }


def generer_jeu_de_donnees(
    chemin: str | Path,
    *,
    chemin_scenarios: str | Path | None = None,
    nb_comptes: int = NB_COMPTES_DEFAUT,
    nb_operations: int = NB_OPERATIONS_DEFAUT,
    debut: date = DEBUT_DEFAUT,
    fin: date = FIN_DEFAUT,
    taux_fraude: float = TAUX_FRAUDE_DEFAUT,
    graine: int = GRAINE_DEFAUT,
) -> dict[str, Any]:
    """Point d'entrée de la phase 1 : génère et écrit le CSV, renvoie les statistiques."""
    _, operations = generer_transactions(
        nb_comptes, nb_operations, debut, fin, taux_fraude, graine
    )
    ecrire_csv(operations, chemin)
    if chemin_scenarios is not None:
        ecrire_scenarios(operations, chemin_scenarios)
    resume = statistiques(operations)
    resume.update(graine=graine, nb_comptes=nb_comptes, fichier=str(chemin))
    return resume
