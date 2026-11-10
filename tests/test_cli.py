"""Phase 6 — interface en ligne de commande (exécution réelle des sous-commandes)."""

from __future__ import annotations

import csv
import json
from pathlib import Path

import pytest

from payguard.cli import construire_parser, main
from tests.conftest import CONFIG_RETENUE, RACINE

PETIT = ["--comptes", "300", "--operations", "5000", "--graine", "3"]


@pytest.fixture(autouse=True)
def dossier_de_travail(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Chaque test s'exécute dans un dossier vide (chemins par défaut relatifs)."""
    monkeypatch.chdir(tmp_path)
    return tmp_path


def test_aide_des_cinq_commandes(capsys: pytest.CaptureFixture[str]) -> None:
    parser = construire_parser()
    for commande in ("generer", "simuler", "analyser", "detecter", "evaluer"):
        with pytest.raises(SystemExit) as sortie:
            parser.parse_args([commande, "--help"])
        assert sortie.value.code == 0
    assert "detecter" in capsys.readouterr().out


def test_generer(capsys: pytest.CaptureFixture[str], tmp_path: Path) -> None:
    assert main(["generer", *PETIT, "-o", "brut.csv", "--scenarios", "sc.csv"]) == 0
    assert "Fichier généré : brut.csv" in capsys.readouterr().out
    with open("brut.csv", encoding="utf-8") as fichier:
        assert next(csv.reader(fichier))[-1] == "est_fraude"
    assert Path("data/payguard.log").is_file(), "le journal est écrit dans un fichier"


def test_chaine_complete_simuler_analyser_detecter_evaluer(
    capsys: pytest.CaptureFixture[str],
) -> None:
    assert main(["simuler", *PETIT]) == 0
    sortie = capsys.readouterr().out
    assert "transactions acceptées" in sortie and Path("data/payguard.db").is_file()

    assert main(["analyser", "--benchmark", "--repetitions", "1", "--figures", "figures"]) == 0
    sortie = capsys.readouterr().out
    assert "résultats identiques : oui" in sortie and len(list(Path("figures").glob("*.png"))) == 6

    assert main(["analyser", "--base", "data/payguard.db", "--figures", "figures_base"]) == 0
    capsys.readouterr()

    assert (
        main(
            [
                "detecter",
                "data/processed/transactions.csv",
                "-c",
                str(CONFIG_RETENUE),
                "--limite",
                "3",
                "--details",
                "--base",
                "data/payguard.db",
            ]
        )
        == 0
    )
    sortie = capsys.readouterr().out
    assert "[ALERTE]" in sortie and "Étiquettes présentes" in sortie and "autres alertes" in sortie
    with open("data/processed/alertes.csv", encoding="utf-8") as fichier:
        alertes = list(csv.DictReader(fichier))
    assert alertes and all(a["regles"] for a in alertes), "chaque alerte indique ses règles"

    reglages = RACINE / "config" / "reglages"
    assert (
        main(
            [
                "evaluer",
                "-c",
                str(CONFIG_RETENUE),
                str(reglages / "prudent.json"),
                "--seuils",
                "3",
                "--scenarios",
                "data/processed/scenarios.csv",
                "--mensuel",
                "--json",
                "eval.json",
            ]
        )
        == 0
    )
    sortie = capsys.readouterr().out
    assert (
        "Coût minimal" in sortie and "référence : aucune alerte" in sortie and "Scénario" in sortie
    )
    resultats = json.loads(Path("eval.json").read_text(encoding="utf-8"))
    assert {r["reglage"] for r in resultats} >= {"regles", "prudent", "regles / seuil 3"}


def test_detecter_fichier_sans_etiquette_desordonne(
    csv_sans_etiquette: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Situation de la soutenance : fichier inconnu, sans
    est_fraude, non trié, configuration intégrée."""
    assert main(["detecter", str(csv_sans_etiquette), "-o", "alertes.csv"]) == 0
    sortie = capsys.readouterr().out
    assert "configuration intégrée" in sortie and "Fichier sans étiquette" in sortie
    lignes = Path("alertes.csv").read_text(encoding="utf-8").splitlines()
    assert len(lignes) > 1 and sortie.count("règles :") == len(lignes) - 1


def test_detecter_en_flux_identique_au_mode_trie(
    csv_simule: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert main(["detecter", str(csv_simule), "-o", "a.csv", "--limite", "0"]) == 0
    assert main(["detecter", str(csv_simule), "-o", "b.csv", "--limite", "0", "--flux"]) == 0
    assert Path("a.csv").read_text(encoding="utf-8") == Path("b.csv").read_text(encoding="utf-8")


def test_detecter_avec_historique(csv_simule: Path, capsys: pytest.CaptureFixture[str]) -> None:
    assert (
        main(
            [
                "detecter",
                str(csv_simule),
                "--historique",
                str(csv_simule),
                "--limite",
                "0",
                "-o",
                "h.csv",
            ]
        )
        == 0
    )
    assert "Historique de référence" in capsys.readouterr().out


def test_erreurs_et_codes_de_sortie(
    tmp_path: Path, csv_simule: Path, csv_sans_etiquette: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    with pytest.raises(SystemExit) as sortie:
        main(["detecter", "absent.csv"])
    assert sortie.value.code == 2
    with pytest.raises(SystemExit):
        main(["generer", "--taux-fraude", "0.9"])
    with pytest.raises(SystemExit):
        main(["generer", "--debut", "01/01/2026"])
    mauvaise = tmp_path / "mauvaise.json"
    mauvaise.write_text('{"seuil_alerte": 2, "regles": [{"nom": "licorne"}]}', encoding="utf-8")
    assert main(["detecter", str(csv_simule), "-c", str(mauvaise)]) == 1
    assert "Erreur" in capsys.readouterr().err
    assert main(["evaluer", "-i", str(csv_sans_etiquette)]) == 1
    assert main(["generer", "--comptes", "10"]) == 1, "erreur métier du générateur"
    with pytest.raises(SystemExit):
        main(["evaluer"])  # aucun fichier par défaut dans un dossier vide
