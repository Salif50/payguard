"""Phase 4 — dépôt SQLite, profils de comptes (Python pur / pandas), analyse."""

from __future__ import annotations

from datetime import timedelta
from pathlib import Path

import pandas as pd
import pytest

from payguard.comptes import TypeTransaction
from payguard.detection.alerte import Alerte
from payguard.donnees import analyse
from payguard.donnees.depot import Depot
from payguard.donnees.profils import ProfilCompte, ProfilsComptes, comparer_implementations
from payguard.exceptions import DonneesInvalides, ParametreInvalide
from payguard.generation.simulation import ResultatSimulation
from payguard.outils.flux import lire_transactions
from tests.conftest import INSTANT, transaction

# --- Dépôt SQLite ---------------------------------------------------------------------


def test_depot_aller_retour(tmp_path: Path, petite_simulation: ResultatSimulation) -> None:
    transactions = petite_simulation.transactions
    with Depot(tmp_path / "base" / "pg.db") as depot:
        assert depot.inserer_transactions(iter(transactions), taille_lot=500) == len(transactions)
        depot.inserer_comptes(petite_simulation.plateforme.comptes)
    with Depot(tmp_path / "base" / "pg.db") as depot:  # relecture après fermeture
        assert depot.compter_transactions() == len(transactions)
        assert list(depot.transactions()) == sorted(transactions)
        assert depot.obtenir_transaction(transactions[0].id_transaction) == transactions[0]
        assert depot.obtenir_transaction("absent") is None
        soldes = depot.solde_comptes()
        assert soldes == {c.id_compte: c.solde for c in petite_simulation.plateforme}


def test_depot_filtres_parametres() -> None:
    t1 = transaction(1)
    t2 = transaction(
        2,
        emetteur="P3",
        destinataire="P1",
        instant=INSTANT + timedelta(days=1),
        type_tx=TypeTransaction.RETRAIT,
        fraude=None,
    )
    t3 = transaction(3, emetteur="P4", destinataire="P5", instant=INSTANT + timedelta(days=2))
    with Depot() as depot:
        depot.inserer_transactions([t1, t2, t3])
        assert [t.id_transaction for t in depot.transactions(id_compte="P1")] == [
            "T00001",
            "T00002",
        ]
        assert [
            t.id_transaction for t in depot.transactions(debut=INSTANT + timedelta(hours=1))
        ] == ["T00002", "T00003"]
        assert [
            t.id_transaction for t in depot.transactions(fin=INSTANT + timedelta(hours=1))
        ] == ["T00001"]
        assert depot.compter_transactions(TypeTransaction.RETRAIT) == 1
        assert depot.obtenir_transaction("T00002").est_fraude is None
        # Une valeur « malveillante » est traitée comme une donnée, jamais comme du SQL.
        assert list(depot.transactions(id_compte="P1' OR '1'='1")) == []
        stats = depot.statistiques_par_type()
        assert stats["transfert"]["nombre"] == 2
        df = depot.lire_dataframe()
        assert len(df) == 3 and pd.api.types.is_datetime64_any_dtype(df["horodatage"])


def test_depot_alertes_et_vidage() -> None:
    t = transaction(1)
    alerte = Alerte(t, 3.0, ("rafale", "nouvel_appareil"), ("3 opérations", "appareil X"))
    with Depot() as depot:
        depot.inserer_transactions([t])
        depot.inserer_alertes([alerte])
        lues = depot.alertes()
        assert lues[0]["regles"] == ["rafale", "nouvel_appareil"] and lues[0]["score"] == 3.0
        depot.vider()
        assert depot.compter_transactions() == 0 and depot.alertes() == []


def test_depot_validation() -> None:
    with pytest.raises(ParametreInvalide):
        Depot().inserer_transactions([], taille_lot=0)


# --- Profils -------------------------------------------------------------------------------


def test_profil_compte_calcule_les_habitudes() -> None:
    historique = [
        transaction(1, montant=100_000, appareil="A", zone="Conakry"),
        transaction(
            2, montant=300_000, appareil="B", zone="Kindia", instant=INSTANT + timedelta(hours=14)
        ),
        transaction(
            3,
            emetteur="P2",
            destinataire="P1",
            montant=50_000,
            instant=INSTANT - timedelta(days=1),
        ),
    ]
    profils = ProfilsComptes.calculer_python(historique)
    p1 = profils["P1"]
    assert (p1.nb_operations, p1.montant_moyen, p1.montant_max) == (2, 200_000, 300_000)
    assert p1.heures == {10: 1, 0: 1}
    assert p1.zones_habituelles(0.5) == {"Conakry", "Kindia"}
    assert p1.appareils_habituels() == {"A", "B"}
    assert p1.derniere_zone == "Kindia"
    assert p1.total_recu == 50_000 and p1.premiere_apparition == INSTANT - timedelta(days=1)
    assert p1.solde_estime == 50_000 - 400_000
    assert p1.part_heures(22, 5) == 0.5
    assert profils["P2"].nb_receptions == 2 and "P9" not in profils
    assert ProfilCompte("X").montant_moyen == 0 and ProfilCompte("X").anciennete(INSTANT) is None


def test_profils_python_et_pandas_identiques(csv_simule: Path) -> None:
    transactions = list(lire_transactions(csv_simule))
    df = analyse.charger_csv(csv_simule)
    python = ProfilsComptes.calculer_python(transactions)
    pandas_ = ProfilsComptes.calculer_pandas(df)
    assert len(python) == len(pandas_) > 100
    assert python == pandas_, python.differences(pandas_)
    mesure = comparer_implementations(transactions, df, repetitions=1)
    assert mesure["identiques"] and mesure["python_s"] > 0 and mesure["pandas_complet_s"] > 0


def test_profils_differences_detecte_un_ecart() -> None:
    a = ProfilsComptes.calculer_python([transaction(1)])
    b = ProfilsComptes.calculer_python([transaction(1, montant=999)])
    assert a != b and len(a.differences(b)) >= 1
    copie = a.copie()
    copie["P1"].nb_operations += 1
    assert a["P1"].nb_operations == 1, "la copie est profonde"
    assert list(a.vers_dataframe().columns)[0] == "nb_operations"


# --- Analyse ------------------------------------------------------------------------------------


def test_analyse_complete_et_figures(csv_simule: Path, tmp_path: Path) -> None:
    df = analyse.charger_csv(csv_simule)
    resultats = analyse.analyser(df, tmp_path / "figures")
    assert len(resultats["figures"]) == 6
    assert all(Path(f).stat().st_size > 10_000 for f in resultats["figures"])
    heures = resultats["fraude_par_heure"]
    assert list(heures.index) == list(range(24)) and heures["transactions"].sum() == len(df)
    assert resultats["fraude_par_zone"]["transactions"].sum() == len(df)
    assert 0 < resultats["concentration"]["part_volume_plus_actifs"] <= 1
    assert set(resultats["delai_median"].index) == {"légitime", "frauduleuse"}
    appareil = resultats["fraude_nouvel_appareil"]
    assert (
        appareil.loc["nouvel appareil", "taux_fraude"]
        > appareil.loc["appareil connu", "taux_fraude"]
    )
    assert list(resultats["montants_par_type"].index) == [
        "depot",
        "retrait",
        "transfert",
        "paiement_marchand",
    ]


def test_concentration_sur_un_cas_connu() -> None:
    df = pd.DataFrame(
        {
            "id_emetteur": ["A"] * 98 + [f"B{i}" for i in range(99)],
            "montant": [1_000] * 98 + [10] * 99,
        }
    )
    resultat = analyse.calculer_concentration_volume(df)
    assert resultat["nb_comptes_retenus"] == 1
    assert resultat["part_volume_plus_actifs"] == pytest.approx(98_000 / (98_000 + 990))
    with pytest.raises(ValueError):
        analyse.calculer_concentration_volume(df, part_comptes=0)


def test_analyse_exige_l_etiquette(csv_sans_etiquette: Path) -> None:
    df = analyse.charger_csv(csv_sans_etiquette)
    assert "est_fraude" not in df.columns
    with pytest.raises(DonneesInvalides):
        analyse.calculer_taux_fraude_par_heure(df)
    assert not analyse.calculer_montants_par_type(df).empty


def test_charger_csv_erreurs(tmp_path: Path) -> None:
    with pytest.raises(DonneesInvalides):
        analyse.charger_csv(tmp_path / "absent.csv")
    chemin = tmp_path / "t.csv"
    chemin.write_text("a,b\n1,2\n", encoding="utf-8")
    with pytest.raises(DonneesInvalides):
        analyse.charger_csv(chemin)
