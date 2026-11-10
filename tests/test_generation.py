"""Phase 1 — générateur de données synthétiques."""

from __future__ import annotations

import csv
import hashlib
from datetime import date, datetime
from pathlib import Path

import pytest

from payguard.exceptions import ParametreInvalide
from payguard.generation.generateur import (
    ecrire_csv,
    generer_jeu_de_donnees,
    generer_transactions,
    statistiques,
    valider_parametres,
)
from payguard.generation.parametres import arrondir_montant, MONTANT_MAX, MONTANT_MIN
from payguard.generation.scenarios import SCENARIOS
from payguard.schema import COLONNES, TYPES_OPERATIONS

PETIT = {"nb_comptes": 400, "nb_operations": 8_000, "graine": 5}


def _empreinte(chemin: Path) -> str:
    return hashlib.sha256(chemin.read_bytes()).hexdigest()


def test_meme_graine_meme_fichier(tmp_path: Path) -> None:
    a, b = tmp_path / "a.csv", tmp_path / "b.csv"
    generer_jeu_de_donnees(a, **PETIT)
    generer_jeu_de_donnees(b, **PETIT)
    assert _empreinte(a) == _empreinte(b)


def test_graine_differente_fichier_different(tmp_path: Path) -> None:
    a, b = tmp_path / "a.csv", tmp_path / "b.csv"
    generer_jeu_de_donnees(a, **PETIT)
    generer_jeu_de_donnees(b, **{**PETIT, "graine": 6})
    assert _empreinte(a) != _empreinte(b)


def test_format_annexe_a(tmp_path: Path) -> None:
    chemin = tmp_path / "t.csv"
    generer_jeu_de_donnees(chemin, **PETIT)
    with chemin.open(encoding="utf-8") as fichier:
        lecteur = csv.DictReader(fichier)
        assert tuple(lecteur.fieldnames or ()) == COLONNES
        lignes = list(lecteur)
    ids = [ligne["id_transaction"] for ligne in lignes]
    assert len(ids) == len(set(ids)), "identifiants non uniques"
    horodatages = [datetime.fromisoformat(ligne["horodatage"]) for ligne in lignes]
    assert horodatages == sorted(horodatages)
    for ligne in lignes:
        assert ligne["type"] in TYPES_OPERATIONS
        assert int(ligne["montant"]) > 0
        assert ligne["est_fraude"] in {"0", "1"}
        assert ligne["id_emetteur"] != ligne["id_destinataire"]


def test_volume_par_defaut_et_taux_de_fraude() -> None:
    """Paramètres par défaut : >= 100 000 transactions, plusieurs
    milliers de comptes, 1 à 2 % de fraude."""
    comptes, operations = generer_transactions()
    resume = statistiques(operations)
    assert resume["nb_transactions"] >= 100_000
    assert len(comptes) >= 2_000
    assert 0.01 <= resume["taux_fraude"] <= 0.02
    debut, fin = datetime.fromisoformat(resume["debut"]), datetime.fromisoformat(resume["fin"])
    assert (fin - debut).days >= 90, "plusieurs mois attendus"
    assert set(resume["par_scenario"]) == set(SCENARIOS), "tous les scénarios doivent apparaître"
    assert set(resume["par_type"]) == set(TYPES_OPERATIONS)


def test_au_moins_quatre_scenarios_distincts() -> None:
    assert len(SCENARIOS) >= 4


def test_montants_differents_selon_le_type() -> None:
    _, operations = generer_transactions(**PETIT)
    medianes = {}
    for type_op in TYPES_OPERATIONS:
        montants = sorted(
            op["montant"] for op in operations if op["type"] == type_op and not op["est_fraude"]
        )
        medianes[type_op] = montants[len(montants) // 2]
    assert medianes["paiement_marchand"] < medianes["transfert"] < medianes["depot"]


def test_taux_fraude_nul() -> None:
    _, operations = generer_transactions(**{**PETIT, "taux_fraude": 0.0})
    assert sum(op["est_fraude"] for op in operations) == 0


@pytest.mark.parametrize(
    "modification",
    [
        {"nb_comptes": 10},
        {"nb_comptes": "1000"},
        {"nb_comptes": True},
        {"nb_operations": 50},
        {"taux_fraude": 0.5},
        {"taux_fraude": -0.01},
        {"taux_fraude": float("nan")},
        {"graine": 4.2},
        {"debut": date(2026, 6, 1), "fin": date(2026, 6, 10)},
        {"debut": "2026-01-01"},
    ],
)
def test_parametres_invalides(modification: dict) -> None:
    parametres = {
        "nb_comptes": 1000,
        "nb_operations": 10_000,
        "debut": date(2026, 1, 1),
        "fin": date(2026, 7, 1),
        "taux_fraude": 0.015,
        "graine": 1,
    }
    parametres.update(modification)
    with pytest.raises(ParametreInvalide):
        valider_parametres(**parametres)


def test_generer_leve_parametre_invalide() -> None:
    with pytest.raises(ParametreInvalide, match="taux_fraude"):
        generer_transactions(taux_fraude=0.9)


def test_arrondi_et_bornes_des_montants() -> None:
    assert arrondir_montant(1_234) == 1_000
    assert arrondir_montant(1_260) == 1_500
    assert arrondir_montant(10) == MONTANT_MIN
    assert arrondir_montant(10**9) == MONTANT_MAX


def test_ecrire_csv_cree_le_dossier(tmp_path: Path) -> None:
    _, operations = generer_transactions(**PETIT)
    chemin = tmp_path / "sous" / "dossier" / "t.csv"
    assert ecrire_csv(operations[:10], chemin) == 10
    assert chemin.read_text(encoding="utf-8").splitlines()[0] == ",".join(COLONNES)
