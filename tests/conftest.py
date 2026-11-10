"""Fixtures partagées par les tests."""

from __future__ import annotations

from datetime import datetime, timedelta
from collections.abc import Iterator
from pathlib import Path

import pytest

from payguard.comptes import (
    Client,
    CompteAgent,
    CompteMarchand,
    ComptePersonnel,
    Plateforme,
    Transaction,
    TypeTransaction,
)
from payguard.journal import reinitialiser_journalisation
from payguard.generation.simulation import (
    ResultatSimulation,
    ecrire_scenarios,
    ecrire_transactions,
    simuler,
)

RACINE = Path(__file__).resolve().parents[1]
CONFIG_RETENUE = RACINE / "config" / "regles.json"
INSTANT = datetime(2026, 3, 14, 10, 0, 0)


def fabriquer_client(numero: int = 1) -> Client:
    return Client(f"CL{numero:04d}", f"Client {numero}", f"+22462{numero:07d}")


@pytest.fixture(autouse=True)
def journal_propre() -> Iterator[None]:
    """Chaque test retrouve un journal ``payguard`` non configuré (la CLI en pose un)."""
    yield
    reinitialiser_journalisation()


@pytest.fixture
def plateforme() -> Plateforme:
    """Plateforme minimale : deux particuliers, un marchand, un agent."""
    p = Plateforme()
    p.ouvrir_compte(ComptePersonnel("P1", fabriquer_client(1), solde_initial=1_000_000))
    p.ouvrir_compte(ComptePersonnel("P2", fabriquer_client(2), solde_initial=200_000))
    p.ouvrir_compte(CompteMarchand("M1", fabriquer_client(3), solde_initial=500_000))
    p.ouvrir_compte(CompteAgent("A1", fabriquer_client(4), solde_initial=50_000_000))
    return p


def transaction(
    numero: int = 1,
    *,
    instant: datetime = INSTANT,
    emetteur: str = "P1",
    destinataire: str = "P2",
    type_tx: TypeTransaction = TypeTransaction.TRANSFERT,
    montant: int = 100_000,
    zone: str = "Conakry",
    appareil: str = "APP-1",
    fraude: bool | None = False,
) -> Transaction:
    """Fabrique une transaction de test lisible."""
    return Transaction(
        f"T{numero:05d}", instant, emetteur, destinataire, type_tx, montant, zone, appareil, fraude
    )


def historique_regulier(
    nb: int = 10, montant: int = 100_000, debut: datetime = INSTANT
) -> list[Transaction]:
    """``nb`` transferts quotidiens de P1, même zone, même appareil, à 10 h."""
    return [
        transaction(i, instant=debut + timedelta(days=i), montant=montant)
        for i in range(1, nb + 1)
    ]


@pytest.fixture(scope="session")
def petite_simulation() -> ResultatSimulation:
    """Simulation réduite mais complète (rapide), partagée par la session."""
    return simuler(nb_comptes=300, nb_operations=6_000, taux_fraude=0.02, graine=123)


@pytest.fixture(scope="session")
def csv_simule(
    petite_simulation: ResultatSimulation, tmp_path_factory: pytest.TempPathFactory
) -> Path:
    """CSV étiqueté de la petite simulation (et son fichier de scénarios à côté)."""
    dossier = tmp_path_factory.mktemp("donnees")
    chemin = dossier / "transactions.csv"
    ecrire_transactions(petite_simulation.transactions, chemin)
    ecrire_scenarios(petite_simulation.scenarios, dossier / "scenarios.csv")
    return chemin


@pytest.fixture(scope="session")
def csv_sans_etiquette(csv_simule: Path, tmp_path_factory: pytest.TempPathFactory) -> Path:
    """Même fichier, sans la colonne est_fraude et dans le
    désordre (comme le jeu de la soutenance)."""
    import csv
    import random

    with csv_simule.open(encoding="utf-8") as fichier:
        lignes = list(csv.DictReader(fichier))
    random.Random(0).shuffle(lignes)
    colonnes = [c for c in lignes[0] if c != "est_fraude"]
    chemin = tmp_path_factory.mktemp("inedit") / "inedit.csv"
    with chemin.open("w", newline="", encoding="utf-8") as fichier:
        ecrivain = csv.DictWriter(fichier, fieldnames=colonnes, extrasaction="ignore")
        ecrivain.writeheader()
        ecrivain.writerows(lignes)
    return chemin
