"""Phase 2 — clients, comptes, transactions, registre."""

from __future__ import annotations

from dataclasses import FrozenInstanceError
from datetime import timedelta

import pytest

from payguard.comptes import (
    Client,
    Compte,
    CompteAgent,
    CompteMarchand,
    ComptePersonnel,
    RegistreComptes,
    Transaction,
    TypeTransaction,
    normaliser_telephone,
)
from payguard.exceptions import (
    CompteDejaExistant,
    CompteGele,
    CompteIntrouvable,
    DonneesInvalides,
    OperationNonAutorisee,
    ParametreInvalide,
    PayGuardError,
    PlafondDepasse,
    SoldeInsuffisant,
)
from tests.conftest import INSTANT, fabriquer_client, transaction

T = TypeTransaction


# --- Client -----------------------------------------------------------------


@pytest.mark.parametrize(
    "saisie",
    ["+224 620 12 34 56", "00224620123456", "620123456", "224-620-12-34-56", "+224.655.00.11.22"],
)
def test_telephone_valide_normalise(saisie: str) -> None:
    assert normaliser_telephone(saisie).startswith("+2246")
    assert len(normaliser_telephone(saisie)) == 13


@pytest.mark.parametrize(
    "saisie", ["+221 77 123 45 67", "520123456", "62012345", "6201234567", "", "abc"]
)
def test_telephone_invalide(saisie: str) -> None:
    with pytest.raises(ParametreInvalide):
        normaliser_telephone(saisie)


def test_client_proprietes_validees() -> None:
    client = Client("C1", "  Mamadou   Diallo ", "620 12 34 56")
    assert client.nom == "Mamadou Diallo"
    assert client.telephone == "+224620123456"
    assert client.telephone_affichage == "+224 620 12 34 56"
    with pytest.raises(ParametreInvalide):
        client.nom = "   "
    with pytest.raises(ParametreInvalide):
        client.telephone = "0123"
    assert client.nom == "Mamadou Diallo", "une affectation refusée ne modifie pas l'objet"
    assert client == Client("C1", "Autre nom", "+224655000000")
    assert len({client, Client("C1", "X", "620000000")}) == 1


# --- Hiérarchie de comptes -----------------------------------------------------


def test_compte_est_abstrait() -> None:
    with pytest.raises(TypeError):
        Compte("X", fabriquer_client())  # type: ignore[abstract]


def test_polymorphisme_frais_et_plafonds() -> None:
    client = fabriquer_client()
    comptes = [ComptePersonnel("P", client), CompteMarchand("M", client), CompteAgent("A", client)]
    frais = [c.calculer_frais(T.RETRAIT, 100_000) for c in comptes]
    assert frais == [1_500, 1_000, 0]
    assert [c.type_compte for c in comptes] == ["personnel", "marchand", "agent"]
    assert (
        comptes[0].plafond_journalier
        < comptes[1].plafond_journalier
        < comptes[2].plafond_journalier
    )
    assert comptes[0].plafond_solde == 50_000_000 and comptes[1].plafond_solde is None
    assert comptes[2].peut_emettre(T.DEPOT) and not comptes[0].peut_emettre(T.DEPOT)
    assert comptes[1].peut_recevoir(T.PAIEMENT_MARCHAND) and not comptes[0].peut_recevoir(
        T.PAIEMENT_MARCHAND
    )


def test_debit_avec_frais_et_credit() -> None:
    compte = ComptePersonnel("P", fabriquer_client(), solde_initial=200_000)
    frais = compte.debiter(100_000, T.TRANSFERT, INSTANT)
    assert frais == 1_000
    assert compte.solde == 99_000
    compte.crediter(1_000, T.TRANSFERT)
    assert compte.solde == 100_000


def test_solde_insuffisant_frais_compris() -> None:
    compte = ComptePersonnel("P", fabriquer_client(), solde_initial=100_000)
    with pytest.raises(SoldeInsuffisant) as info:
        compte.debiter(100_000, T.TRANSFERT, INSTANT)  # 100 000 + 1 000 de frais
    assert info.value.montant_requis == 101_000
    assert compte.solde == 100_000


def test_plafond_par_operation() -> None:
    compte = ComptePersonnel("P", fabriquer_client(), solde_initial=40_000_000)
    with pytest.raises(PlafondDepasse, match="par opération"):
        compte.debiter(5_000_001, T.TRANSFERT, INSTANT)


def test_plafond_journalier_puis_jour_suivant() -> None:
    compte = ComptePersonnel("P", fabriquer_client(), solde_initial=40_000_000)
    for _ in range(3):
        compte.debiter(5_000_000, T.PAIEMENT_MARCHAND, INSTANT)
    with pytest.raises(PlafondDepasse, match="journalier"):
        compte.debiter(1_000, T.PAIEMENT_MARCHAND, INSTANT)
    compte.debiter(
        1_000, T.PAIEMENT_MARCHAND, INSTANT + timedelta(days=1)
    )  # nouveau jour : cumul remis à zéro


def test_plafond_de_solde_au_credit() -> None:
    compte = ComptePersonnel("P", fabriquer_client(), solde_initial=49_000_000)
    with pytest.raises(PlafondDepasse, match="de solde"):
        compte.crediter(2_000_000, T.DEPOT)


def test_compte_gele() -> None:
    compte = ComptePersonnel("P", fabriquer_client(), solde_initial=100_000)
    compte.geler()
    with pytest.raises(CompteGele):
        compte.debiter(1_000, T.TRANSFERT, INSTANT)
    with pytest.raises(CompteGele):
        compte.crediter(1_000, T.TRANSFERT)
    compte.degeler()
    compte.debiter(1_000, T.TRANSFERT, INSTANT)


def test_operation_non_autorisee_et_montant_invalide() -> None:
    compte = ComptePersonnel("P", fabriquer_client(), solde_initial=100_000)
    with pytest.raises(OperationNonAutorisee):
        compte.debiter(1_000, T.DEPOT, INSTANT)
    for montant in (0, -5, 10.5, True):
        with pytest.raises(ParametreInvalide):
            compte.debiter(montant, T.TRANSFERT, INSTANT)  # type: ignore[arg-type]


def test_hierarchie_des_exceptions() -> None:
    for classe in (
        SoldeInsuffisant,
        PlafondDepasse,
        CompteGele,
        CompteIntrouvable,
        ParametreInvalide,
    ):
        assert issubclass(classe, PayGuardError)


def test_constructeur_compte_invalide() -> None:
    with pytest.raises(ParametreInvalide):
        ComptePersonnel("", fabriquer_client())
    with pytest.raises(ParametreInvalide):
        ComptePersonnel("P", "pas un client")  # type: ignore[arg-type]
    with pytest.raises(ParametreInvalide):
        ComptePersonnel("P", fabriquer_client(), solde_initial=-1)


def test_methodes_speciales_compte() -> None:
    a = ComptePersonnel("P2", fabriquer_client(), solde_initial=10)
    b = ComptePersonnel("P1", fabriquer_client(), solde_initial=99)
    assert a == ComptePersonnel("P2", fabriquer_client(9))
    assert hash(a) == hash("P2")
    assert sorted([a, b]) == [b, a]
    assert "ComptePersonnel" in repr(a) and "solde=10" in repr(a)


# --- Transaction ----------------------------------------------------------------


def test_transaction_immuable_et_hachable() -> None:
    t = transaction()
    with pytest.raises(FrozenInstanceError):
        t.montant = 1  # type: ignore[misc]
    assert t in {t}
    assert t == transaction()


def test_transaction_ordre_chronologique() -> None:
    tardive = transaction(1, instant=INSTANT + timedelta(minutes=1))
    tot = transaction(2)
    assert sorted([tardive, tot]) == [tot, tardive]


@pytest.mark.parametrize(
    "modification", [{"montant": 0}, {"montant": -1}, {"zone": ""}, {"emetteur": " "}]
)
def test_transaction_invalide(modification: dict) -> None:
    with pytest.raises(DonneesInvalides):
        transaction(**modification)


def test_transaction_depuis_ligne_tolerante() -> None:
    ligne = {
        "id_transaction": " TX1 ",
        "horodatage": "2026-03-14T08:42:10Z",
        "id_emetteur": "P1",
        "id_destinataire": "M1",
        "type": "Paiement_Marchand",
        "montant": "1500.0",
        "zone": "Kindia",
        "appareil_id": "APP-1",
    }
    t = Transaction.depuis_ligne(ligne)
    assert t.id_transaction == "TX1" and t.type is T.PAIEMENT_MARCHAND and t.montant == 1_500
    assert t.est_fraude is None and t.horodatage.tzinfo is None
    assert Transaction.depuis_ligne({**ligne, "est_fraude": "1"}).est_fraude is True
    assert t.vers_ligne()["est_fraude"] == ""


@pytest.mark.parametrize(
    "modification",
    [
        {"type": "virement"},
        {"montant": "abc"},
        {"montant": "-3"},
        {"horodatage": "hier"},
        {"zone": ""},
        {"est_fraude": "peut-être"},
    ],
)
def test_transaction_depuis_ligne_invalide(modification: dict) -> None:
    ligne = {
        "id_transaction": "TX1",
        "horodatage": "2026-03-14T08:42:10",
        "id_emetteur": "P1",
        "id_destinataire": "M1",
        "type": "transfert",
        "montant": "1500",
        "zone": "Kindia",
        "appareil_id": "APP-1",
        **modification,
    }
    with pytest.raises(DonneesInvalides):
        Transaction.depuis_ligne(ligne)


# --- Registre -------------------------------------------------------------------


def test_registre_collection_naturelle() -> None:
    client = fabriquer_client()
    comptes = [
        ComptePersonnel("P2", client, solde_initial=300),
        CompteMarchand("M1", client, solde_initial=100),
        ComptePersonnel("P1", client, solde_initial=200),
    ]
    registre = RegistreComptes(comptes)
    assert len(registre) == 3
    assert "P1" in registre and comptes[0] in registre and "X" not in registre
    assert registre["M1"] is comptes[1]
    assert [c.id_compte for c in sorted(registre)] == ["M1", "P1", "P2"]
    assert [c.id_compte for c in registre.tries(cle=lambda c: c.solde, decroissant=True)] == [
        "P2",
        "P1",
        "M1",
    ]
    personnels = registre.par_type(ComptePersonnel)
    assert isinstance(personnels, RegistreComptes) and len(personnels) == 2
    assert len(registre.filtrer(lambda c: c.solde >= 200)) == 2
    assert registre.solde_total == 600
    assert [c.id_compte for c in registre] == ["P2", "M1", "P1"], "ordre d'insertion conservé"


def test_registre_erreurs() -> None:
    registre = RegistreComptes([ComptePersonnel("P1", fabriquer_client())])
    with pytest.raises(CompteDejaExistant):
        registre.ajouter(ComptePersonnel("P1", fabriquer_client()))
    with pytest.raises(CompteIntrouvable):
        registre["absent"]
    with pytest.raises(TypeError):
        registre.ajouter("P9")  # type: ignore[arg-type]
    assert registre.retirer("P1").id_compte == "P1" and len(registre) == 0
