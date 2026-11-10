"""Phase 3 — décorateurs, gestionnaires de contexte, lecture en flux, fenêtre glissante."""

from __future__ import annotations

import inspect
import logging
from datetime import timedelta
from pathlib import Path

import pytest

from payguard.comptes import ComptePersonnel, TypeTransaction
from payguard.exceptions import DonneesInvalides, ParametreInvalide
from payguard.outils.contextes import TransactionAtomique, transaction_atomique
from payguard.outils.decorateurs import chronometre, journaliser, reessayer
from payguard.outils.flux import (
    FenetreGlissanteParCompte,
    RapportLecture,
    lire_par_blocs,
    lire_transactions,
)
from tests.conftest import INSTANT, fabriquer_client, transaction

# --- Décorateurs ------------------------------------------------------------------


def test_chronometre_mesure_et_preserve_metadonnees(caplog: pytest.LogCaptureFixture) -> None:
    @chronometre
    def addition(a: int, b: int = 2) -> int:
        """Additionne."""
        return a + b

    with caplog.at_level(logging.INFO):
        assert addition(1) == 3
    assert addition.__name__ == "addition" and addition.__doc__ == "Additionne."
    assert list(inspect.signature(addition).parameters) == ["a", "b"]
    assert addition.derniere_duree is not None and addition.derniere_duree >= 0
    assert "addition exécutée en" in caplog.text


def test_journaliser_trace_et_relance(caplog: pytest.LogCaptureFixture) -> None:
    @journaliser
    def diviser(a: int, b: int) -> float:
        return a / b

    with caplog.at_level(logging.DEBUG):
        assert diviser(4, b=2) == 2
        with pytest.raises(ZeroDivisionError):
            diviser(1, 0)
    assert "Appel" in caplog.text and "b=2" in caplog.text and "ZeroDivisionError" in caplog.text


def test_reessayer_finit_par_reussir() -> None:
    appels = []

    @reessayer(n=3, delai=0)
    def instable() -> str:
        appels.append(1)
        if len(appels) < 3:
            raise ConnectionError("temporaire")
        return "ok"

    assert instable() == "ok" and len(appels) == 3


def test_reessayer_abandonne_apres_n_essais() -> None:
    appels = []

    @reessayer(n=2, delai=0, exceptions=(ConnectionError,))
    def toujours_en_echec() -> None:
        appels.append(1)
        raise ConnectionError("panne")

    with pytest.raises(ConnectionError):
        toujours_en_echec()
    assert len(appels) == 2


def test_reessayer_ne_reessaie_pas_les_autres_exceptions() -> None:
    appels = []

    @reessayer(n=5, delai=0, exceptions=(ConnectionError,))
    def bogue() -> None:
        appels.append(1)
        raise ValueError("erreur de programmation")

    with pytest.raises(ValueError):
        bogue()
    assert len(appels) == 1


@pytest.mark.parametrize("n, delai", [(0, 0.1), (2, -1)])
def test_reessayer_parametres_invalides(n: int, delai: float) -> None:
    with pytest.raises(ValueError):
        reessayer(n=n, delai=delai)


# --- Gestionnaires de contexte ---------------------------------------------------------


@pytest.mark.parametrize("fabrique", [TransactionAtomique, transaction_atomique])
def test_contexte_restaure_en_cas_d_echec(fabrique) -> None:
    a = ComptePersonnel("A", fabriquer_client(), solde_initial=100_000)
    b = ComptePersonnel("B", fabriquer_client(), solde_initial=0)
    b.geler()
    with pytest.raises(Exception):
        with fabrique(a, b):
            a.debiter(50_000, TypeTransaction.TRANSFERT, INSTANT)
            assert a.solde < 100_000
            b.crediter(50_000, TypeTransaction.TRANSFERT)
    assert a.solde == 100_000 and b.solde == 0


@pytest.mark.parametrize("fabrique", [TransactionAtomique, transaction_atomique])
def test_contexte_conserve_en_cas_de_succes(fabrique) -> None:
    a = ComptePersonnel("A", fabriquer_client(), solde_initial=100_000)
    b = ComptePersonnel("B", fabriquer_client(), solde_initial=0)
    with fabrique(a, b):
        a.debiter(50_000, TypeTransaction.TRANSFERT, INSTANT)
        b.crediter(50_000, TypeTransaction.TRANSFERT)
    assert (a.solde, b.solde) == (49_500, 50_000)


def test_contexte_classe_indique_l_annulation() -> None:
    a = ComptePersonnel("A", fabriquer_client(), solde_initial=10)
    contexte = TransactionAtomique(a)
    with pytest.raises(RuntimeError):
        with contexte:
            raise RuntimeError
    assert contexte.annulee is True


def test_contexte_participants_invalides() -> None:
    with pytest.raises(ValueError):
        TransactionAtomique()
    with pytest.raises(TypeError):
        with transaction_atomique(object()):  # type: ignore[arg-type]
            pass


# --- Lecture en flux ----------------------------------------------------------------------


def test_lecture_par_blocs(csv_simule: Path) -> None:
    rapport = RapportLecture()
    blocs = list(lire_par_blocs(csv_simule, taille_bloc=1_000, rapport=rapport))
    assert all(len(b) == 1_000 for b in blocs[:-1]) and 0 < len(blocs[-1]) <= 1_000
    assert sum(map(len, blocs)) == rapport.lignes_lues
    assert rapport.etiquette_presente is True


def test_lecture_est_paresseuse(csv_simule: Path) -> None:
    flux = lire_transactions(csv_simule)
    assert inspect.isgenerator(flux)
    premiere = next(flux)
    assert premiere.id_transaction
    flux.close()


def test_lecture_tolerante_et_stricte(tmp_path: Path) -> None:
    chemin = tmp_path / "t.csv"
    chemin.write_text(
        "﻿id_transaction,horodatage,id_emetteur,id_destinataire,type,montant,zone,appareil_id\n"
        "T1,2026-01-01T10:00:00,P1,P2,transfert,1000,Conakry,X\n"
        "\n"
        "T2,pas une date,P1,P2,transfert,1000,Conakry,X\n"
        "T3,2026-01-01T11:00:00,P1,P2,TRANSFERT,1000,Conakry,X\n",
        encoding="utf-8",
    )
    rapport = RapportLecture()
    ids = [t.id_transaction for t in lire_transactions(chemin, rapport=rapport)]
    assert ids == ["T1", "T3"]
    assert (
        rapport.lignes_rejetees == 1
        and rapport.erreurs[0][0] == 4
        and not rapport.etiquette_presente
    )
    with pytest.raises(DonneesInvalides, match="ligne 4"):
        list(lire_transactions(chemin, strict=True))


def test_lecture_entete_incomplet_ou_fichier_absent(tmp_path: Path) -> None:
    chemin = tmp_path / "t.csv"
    chemin.write_text("id_transaction,montant\nT1,5\n", encoding="utf-8")
    with pytest.raises(DonneesInvalides, match="colonnes absentes"):
        list(lire_transactions(chemin))
    with pytest.raises(DonneesInvalides, match="introuvable"):
        list(lire_transactions(tmp_path / "absent.csv"))
    with pytest.raises(ParametreInvalide):
        list(lire_par_blocs(chemin, taille_bloc=0))


# --- Fenêtre glissante ---------------------------------------------------------------------


def _flux() -> list:
    # P1 : 4 transactions espacées de 10 min ; P2 : 1 transaction intercalée.
    flux = [transaction(i, instant=INSTANT + timedelta(minutes=10 * i)) for i in range(4)]
    flux.insert(
        2,
        transaction(99, emetteur="P2", destinataire="P1", instant=INSTANT + timedelta(minutes=15)),
    )
    return flux


def test_fenetre_glissante_debut_partiel_et_fin() -> None:
    fenetres = list(FenetreGlissanteParCompte(_flux(), taille=3))
    assert len(fenetres) == 5, "une fenêtre par transaction, aucune en trop en fin de flux"
    tailles_p1 = [len(f) for compte, f in fenetres if compte == "P1"]
    assert tailles_p1 == [1, 2, 3, 3], "fenêtres partielles au début, puis glissantes"
    compte, derniere = fenetres[-1]
    assert [t.id_transaction for t in derniere] == ["T00001", "T00002", "T00003"]
    assert ("P2", (fenetres[2][1][0],)) == fenetres[2]


def test_fenetre_glissante_completes_seulement_et_duree() -> None:
    completes = list(FenetreGlissanteParCompte(_flux(), taille=3, completes_seulement=True))
    assert [len(f) for _, f in completes] == [3, 3]
    temporelles = list(FenetreGlissanteParCompte(_flux(), taille=10, duree=timedelta(minutes=15)))
    assert [len(f) for c, f in temporelles if c == "P1"] == [1, 2, 2, 2]


def test_fenetre_glissante_iterateur_et_validation() -> None:
    iterateur = FenetreGlissanteParCompte([], taille=2)
    assert iter(iterateur) is iterateur
    with pytest.raises(StopIteration):
        next(iterateur)
    with pytest.raises(ParametreInvalide):
        FenetreGlissanteParCompte([], taille=0)
    with pytest.raises(ParametreInvalide):
        FenetreGlissanteParCompte([], duree=timedelta(0))
