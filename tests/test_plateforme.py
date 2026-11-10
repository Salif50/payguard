"""Phase 2 — plateforme, atomicité des opérations, simulation."""

from __future__ import annotations

import pytest

from payguard.comptes import Plateforme, TypeTransaction
from payguard.exceptions import (
    CompteGele,
    CompteIntrouvable,
    OperationNonAutorisee,
    PlafondDepasse,
    SoldeInsuffisant,
)
from payguard.generation.simulation import ResultatSimulation
from tests.conftest import INSTANT


def _soldes(plateforme: Plateforme) -> dict[str, int]:
    return {c.id_compte: c.solde for c in plateforme}


def test_quatre_operations_et_frais(plateforme: Plateforme) -> None:
    plateforme.deposer("A1", "P2", 100_000, horodatage=INSTANT)
    plateforme.transferer("P1", "P2", 100_000, horodatage=INSTANT)  # frais 1 %
    plateforme.payer("P2", "M1", 50_000, horodatage=INSTANT)  # gratuit
    plateforme.retirer("P1", "A1", 200_000, horodatage=INSTANT)  # frais 1,5 %
    assert _soldes(plateforme) == {
        "P1": 1_000_000 - 101_000 - 203_000,
        "P2": 200_000 + 100_000 + 100_000 - 50_000,
        "M1": 550_000,
        "A1": 50_000_000 - 100_000 + 200_000,
    }
    assert plateforme.revenus == 1_000 + 3_000
    assert len(plateforme.historique) == 4
    assert [t.type for t in plateforme.historique][0] is TypeTransaction.DEPOT


def test_conservation_de_la_monnaie(plateforme: Plateforme) -> None:
    """Masse monétaire + revenus de la plateforme constante : rien n'est créé ni détruit."""
    total_initial = plateforme.comptes.solde_total
    plateforme.transferer("P1", "P2", 333_333, horodatage=INSTANT)
    plateforme.retirer("P2", "A1", 99_999, horodatage=INSTANT)
    assert plateforme.comptes.solde_total + plateforme.revenus == total_initial


def test_transfert_atomique_si_le_credit_echoue(plateforme: Plateforme) -> None:
    """La jambe débit réussit, la jambe crédit échoue (compte gelé) : tout est annulé."""
    avant = _soldes(plateforme)
    plateforme.compte("P2").geler()
    with pytest.raises(CompteGele):
        plateforme.transferer("P1", "P2", 100_000, horodatage=INSTANT)
    assert _soldes(plateforme) == avant
    assert plateforme.historique == () and plateforme.revenus == 0
    # Le cumul journalier de P1 a aussi été restauré : il peut encore dépenser son plafond complet.
    plateforme.compte("P1").crediter(30_000_000, TypeTransaction.DEPOT)
    for _ in range(3):
        plateforme.payer("P1", "M1", 5_000_000, horodatage=INSTANT)


def test_transfert_atomique_si_plafond_de_solde_du_destinataire(plateforme: Plateforme) -> None:
    plateforme.compte("P2").crediter(49_800_000, TypeTransaction.DEPOT)
    avant = _soldes(plateforme)
    with pytest.raises(PlafondDepasse):
        plateforme.transferer("P1", "P2", 500_000, horodatage=INSTANT)
    assert _soldes(plateforme) == avant


@pytest.mark.parametrize(
    "appel, exception",
    [
        (lambda p: p.transferer("P2", "P1", 500_000, horodatage=INSTANT), SoldeInsuffisant),
        (lambda p: p.transferer("P1", "INCONNU", 1_000, horodatage=INSTANT), CompteIntrouvable),
        (lambda p: p.transferer("P1", "P1", 1_000, horodatage=INSTANT), OperationNonAutorisee),
        (lambda p: p.payer("P1", "P2", 1_000, horodatage=INSTANT), OperationNonAutorisee),
        (lambda p: p.deposer("P1", "P2", 1_000, horodatage=INSTANT), OperationNonAutorisee),
        (lambda p: p.executer("virement", "P1", "P2", 1_000), Exception),
    ],
)
def test_operations_rejetees_sans_effet(plateforme: Plateforme, appel, exception) -> None:
    avant = _soldes(plateforme)
    with pytest.raises(exception):
        appel(plateforme)
    assert _soldes(plateforme) == avant and plateforme.historique == ()


def test_compteur_de_rejets(plateforme: Plateforme) -> None:
    for _ in range(2):
        with pytest.raises(SoldeInsuffisant):
            plateforme.transferer("P2", "P1", 4_000_000, horodatage=INSTANT)
    with pytest.raises(PlafondDepasse):
        plateforme.transferer("P1", "P2", 6_000_000, horodatage=INSTANT)
    assert plateforme.rejets == {"SoldeInsuffisant": 2, "PlafondDepasse": 1}


def test_operations_groupees_tout_ou_rien(plateforme: Plateforme) -> None:
    avant = _soldes(plateforme)
    with pytest.raises(SoldeInsuffisant):
        with plateforme.operations_groupees("P2", "M1", "P1"):
            plateforme.payer("P2", "M1", 150_000, horodatage=INSTANT)  # réussit
            plateforme.payer(
                "P2", "M1", 150_000, horodatage=INSTANT
            )  # échoue : le premier est annulé
    assert _soldes(plateforme) == avant and plateforme.historique == ()
    with plateforme.operations_groupees():
        plateforme.payer("P2", "M1", 50_000, horodatage=INSTANT)
    assert len(plateforme.historique) == 1


def test_methodes_speciales_plateforme(plateforme: Plateforme) -> None:
    assert len(plateforme) == 4
    assert "P1" in plateforme and "Z" not in plateforme
    assert {c.id_compte for c in plateforme} == {"P1", "P2", "M1", "A1"}
    assert "Plateforme(" in repr(plateforme)
    assert plateforme.statistiques()["nb_comptes"] == 4


def test_simulation_passe_par_les_regles_metier(petite_simulation: ResultatSimulation) -> None:
    resume = petite_simulation.resume()
    assert resume["nb_transactions_acceptees"] > 6_000
    assert (
        resume["nb_rejets"] > 0
    ), "le générateur produit des opérations non provisionnées, rejetées"
    assert set(resume["rejets_par_motif"]) <= {
        "SoldeInsuffisant",
        "PlafondDepasse",
        "CompteGele",
        "OperationNonAutorisee",
    }
    assert all(c.solde >= 0 for c in petite_simulation.plateforme)
    assert 0.01 <= resume["taux_fraude"] <= 0.03
    assert set(petite_simulation.scenarios) == {
        t.id_transaction for t in petite_simulation.transactions if t.est_fraude
    }
