"""Phase 5 — règles, moteur, alertes, configuration, évaluation."""

from __future__ import annotations

import json
from dataclasses import replace
from datetime import timedelta
from pathlib import Path

import pytest

from payguard.comptes import TypeTransaction
from payguard.detection import (
    Alerte,
    MoteurDeRegles,
    Regle,
    RegleChangementZone,
    RegleCompteRecentVide,
    RegleHoraireInhabituel,
    RegleMontantAnormal,
    RegleMontantEleve,
    RegleNouvelAppareil,
    RegleRafale,
    ResultatRegle,
    charger_configuration,
    configuration_par_defaut,
)
from payguard.detection.configuration import ConfigurationMoteur, enregistrer_configuration
from payguard.detection.evaluation import (
    contribution_des_regles,
    detection_par_scenario,
    evaluer,
    evaluer_seuils,
    evolution_mensuelle,
    references,
)
from payguard.donnees.profils import ProfilCompte, ProfilsComptes
from payguard.exceptions import ConfigurationInvalide, DonneesInvalides, ParametreInvalide
from payguard.outils.flux import lire_transactions
from tests.conftest import CONFIG_RETENUE, INSTANT, historique_regulier, transaction


def profil_de(transactions: list) -> ProfilCompte:
    """Profil de P1 construit à partir d'un historique."""
    return ProfilsComptes.calculer_python(transactions).obtenir_ou_creer("P1")


# --- Règles ---------------------------------------------------------------------------


def test_montant_anormal() -> None:
    regle = RegleMontantAnormal(poids=2, facteur=4, min_operations=3)
    profil = profil_de(historique_regulier(5, montant=100_000))
    resultat = regle.evaluer(transaction(50, montant=500_000), profil)
    assert resultat.declenchee and resultat.poids == 2 and "5.0 × la moyenne" in resultat.motif
    assert not regle.evaluer(transaction(50, montant=300_000), profil).declenchee
    assert not regle.evaluer(
        transaction(50, montant=500_000), profil_de(historique_regulier(2))
    ).declenchee


def test_montant_eleve_et_types_concernes() -> None:
    regle = RegleMontantEleve(seuil=1_000_000, types_operations=["retrait", "transfert"])
    assert regle.evaluer(transaction(montant=1_000_000), ProfilCompte("P1")).declenchee
    assert not regle.evaluer(transaction(montant=999_999), ProfilCompte("P1")).declenchee
    depot = transaction(type_tx=TypeTransaction.DEPOT, montant=5_000_000)
    assert not regle.concerne(depot) and regle.concerne(transaction())


def test_rafale() -> None:
    regle = RegleRafale(nb_operations=3, fenetre_minutes=10)
    historique = [transaction(i, instant=INSTANT + timedelta(minutes=2 * i)) for i in range(2)]
    profil = profil_de(historique)
    assert regle.evaluer(transaction(9, instant=INSTANT + timedelta(minutes=5)), profil).declenchee
    assert not regle.evaluer(
        transaction(9, instant=INSTANT + timedelta(minutes=30)), profil
    ).declenchee


def test_horaire_inhabituel() -> None:
    regle = RegleHoraireInhabituel(heure_debut=0, heure_fin=5, part_max=0.1)
    diurne = profil_de(historique_regulier(10))
    nuit = transaction(50, instant=INSTANT.replace(hour=3))
    assert regle.evaluer(nuit, diurne).declenchee
    assert not regle.evaluer(transaction(50), diurne).declenchee
    noctambule = profil_de(
        [transaction(i, instant=INSTANT.replace(hour=2) + timedelta(days=i)) for i in range(5)]
    )
    assert not regle.evaluer(nuit, noctambule).declenchee
    plage_minuit = RegleHoraireInhabituel(heure_debut=23, heure_fin=2)
    assert plage_minuit.evaluer(
        transaction(50, instant=INSTANT.replace(hour=23)), diurne
    ).declenchee


def test_changement_zone_voyage_impossible_et_zone_inconnue() -> None:
    regle = RegleChangementZone(delai_minutes=120, min_operations=5)
    historique = historique_regulier(6)
    profil = profil_de(historique)
    juste_apres = historique[-1].horodatage + timedelta(minutes=30)
    resultat = regle.evaluer(transaction(50, instant=juste_apres, zone="Kankan"), profil)
    assert resultat.declenchee and "30 min après" in resultat.motif
    bien_plus_tard = juste_apres + timedelta(days=3)
    assert (
        "jamais ou rarement"
        in regle.evaluer(transaction(50, instant=bien_plus_tard, zone="Kankan"), profil).motif
    )
    assert not regle.evaluer(transaction(50, instant=bien_plus_tard), profil).declenchee


def test_nouvel_appareil() -> None:
    regle = RegleNouvelAppareil(min_operations=2)
    profil = profil_de(historique_regulier(3))
    assert regle.evaluer(transaction(50, appareil="APP-VOLE"), profil).declenchee
    assert not regle.evaluer(transaction(50), profil).declenchee
    assert not regle.evaluer(
        transaction(50, appareil="APP-VOLE"), profil_de(historique_regulier(1))
    ).declenchee


def test_compte_recent_vide() -> None:
    regle = RegleCompteRecentVide(anciennete_max_jours=7, part_min=0.8)
    entree = transaction(1, emetteur="P9", destinataire="P1", montant=1_000_000)
    profil = profil_de([entree])
    sortie = transaction(2, instant=INSTANT + timedelta(minutes=20), montant=950_000)
    assert regle.evaluer(sortie, profil).declenchee
    assert not regle.evaluer(replace(sortie, montant=100_000), profil).declenchee
    assert not regle.evaluer(
        replace(sortie, horodatage=INSTANT + timedelta(days=30)), profil
    ).declenchee


@pytest.mark.parametrize(
    "fabrique",
    [
        lambda: RegleMontantAnormal(facteur=1),
        lambda: RegleMontantAnormal(min_operations=0),
        lambda: RegleRafale(nb_operations=1),
        lambda: RegleRafale(fenetre_minutes=0),
        lambda: RegleHoraireInhabituel(heure_debut=3, heure_fin=3),
        lambda: RegleHoraireInhabituel(heure_debut=25),
        lambda: RegleMontantEleve(seuil=-5),
        lambda: RegleNouvelAppareil(poids=-1),
        lambda: RegleCompteRecentVide(part_min=0),
        lambda: RegleMontantEleve(types_operations=["virement"]),
        lambda: RegleMontantEleve(types_operations="retrait"),
        lambda: RegleMontantEleve(identifiant=""),
    ],
)
def test_parametres_de_regle_invalides(fabrique) -> None:
    with pytest.raises((ParametreInvalide, DonneesInvalides)):
        fabrique()


def test_registre_et_fabrique_de_regles() -> None:
    assert {
        "montant_anormal",
        "rafale",
        "horaire_inhabituel",
        "changement_zone",
        "nouvel_appareil",
        "compte_recent_vide",
        "montant_eleve",
    } <= set(Regle.registre())
    regle = Regle.creer("rafale", 3.0, nb_operations=4)
    assert (
        isinstance(regle, RegleRafale)
        and regle.poids == 3
        and regle.parametres()["nb_operations"] == 4
    )
    assert (
        Regle.creer("montant_eleve", identifiant="palier_bas", seuil=10).identifiant
        == "palier_bas"
    )
    with pytest.raises(ConfigurationInvalide, match="inconnue"):
        Regle.creer("pleine_lune")
    with pytest.raises(ConfigurationInvalide, match="paramètre"):
        Regle.creer("rafale", seuil_magique=3)
    with pytest.raises(ConfigurationInvalide):
        Regle.creer("rafale", nb_operations=-2)


def test_nouvelle_regle_sans_modifier_le_moteur() -> None:
    """Patron Stratégie : une règle écrite après coup s'intègre
    sans toucher au moteur ni à la configuration."""

    class RegleMarchandSuspect(Regle):
        nom = "test_marchand_suspect"

        def evaluer(self, transaction, profil):  # noqa: ANN001, ANN201
            if transaction.id_destinataire == "M666":
                return self._declencher("destinataire sur liste noire")
            return self._ignorer()

    moteur = MoteurDeRegles([RegleMarchandSuspect(poids=5)], seuil_alerte=5)
    alertes = list(moteur.detecter([transaction(1), transaction(2, destinataire="M666")]))
    assert [a.id_transaction for a in alertes] == ["T00002"]
    assert "test_marchand_suspect" in Regle.registre()


# --- Moteur -----------------------------------------------------------------------------------


def test_moteur_score_somme_des_poids() -> None:
    moteur = MoteurDeRegles(
        [RegleMontantEleve(poids=1.5, seuil=10), RegleNouvelAppareil(poids=2, min_operations=1)],
        seuil_alerte=3,
    )
    profil = profil_de(historique_regulier(2))
    evaluation = moteur.evaluer(transaction(9, appareil="NEUF"), profil)
    assert evaluation.score == 3.5 and evaluation.regles == ("montant_eleve", "nouvel_appareil")
    assert evaluation.est_alerte(3) and not evaluation.est_alerte(4)
    assert moteur.evaluer(transaction(9), None).score == 1.5


def test_moteur_ajout_retrait_et_methodes_speciales() -> None:
    moteur = MoteurDeRegles([RegleRafale()], seuil_alerte=1)
    moteur.ajouter_regle(RegleNouvelAppareil())
    assert (
        len(moteur) == 2
        and "rafale" in moteur
        and [r.nom for r in moteur] == ["rafale", "nouvel_appareil"]
    )
    with pytest.raises(ParametreInvalide):
        moteur.ajouter_regle(RegleRafale())
    moteur.ajouter_regle(RegleRafale(identifiant="rafale_longue", fenetre_minutes=60))
    assert isinstance(moteur.retirer_regle("rafale"), RegleRafale) and "rafale" not in moteur
    with pytest.raises(KeyError):
        moteur.retirer_regle("rafale")
    with pytest.raises(TypeError):
        moteur.ajouter_regle("rafale")  # type: ignore[arg-type]
    with pytest.raises(ParametreInvalide):
        moteur.seuil_alerte = 0
    assert "MoteurDeRegles(" in repr(moteur)


def test_moteur_causal_et_aveugle_aux_etiquettes(csv_simule: Path) -> None:
    """Les étiquettes n'influencent rien, et le profil ne
    contient jamais la transaction évaluée."""
    transactions = sorted(lire_transactions(csv_simule))
    moteur = configuration_par_defaut().construire_moteur()
    avec = [(a.id_transaction, a.score) for a in moteur.detecter(transactions)]
    inversees = [
        replace(t, est_fraude=None if t.est_fraude is None else not t.est_fraude)
        for t in transactions
    ]
    sans = [replace(t, est_fraude=None) for t in transactions]
    assert avec == [(a.id_transaction, a.score) for a in moteur.detecter(inversees)]
    assert avec == [(a.id_transaction, a.score) for a in moteur.detecter(sans)]
    # Causalité : la première transaction de chaque émetteur est évaluée avec un profil vide.
    premiere = transactions[0]
    evaluation = next(moteur.analyser([premiere]))
    assert "nouvel_appareil" not in evaluation.regles and "rafale" not in evaluation.regles


def test_moteur_n_altere_pas_les_profils_fournis() -> None:
    historique = ProfilsComptes.calculer_python(historique_regulier(3))
    moteur = MoteurDeRegles([RegleNouvelAppareil()], seuil_alerte=1)
    alertes = list(
        moteur.detecter(
            [transaction(50, appareil="NEUF", instant=INSTANT + timedelta(days=9))], historique
        )
    )
    assert len(alertes) == 1 and historique["P1"].nb_operations == 3


def test_moteur_signale_desordre_chronologique(caplog: pytest.LogCaptureFixture) -> None:
    moteur = MoteurDeRegles([RegleRafale()])
    list(moteur.analyser([transaction(1, instant=INSTANT + timedelta(hours=1)), transaction(2)]))
    assert "ordre chronologique" in caplog.text


# --- Alerte ------------------------------------------------------------------------------------


def test_alerte_validation_tri_et_affichage() -> None:
    forte = Alerte(transaction(1), 4.0, ("rafale",), ("3 opérations en 5 min",))
    faible = Alerte(transaction(2), 2.0, ("nouvel_appareil",), ("appareil inconnu",))
    assert sorted([faible, forte], reverse=True) == [forte, faible]
    assert "rafale : 3 opérations" in str(forte) and "[ALERTE] T00001" in str(forte)
    assert forte.vers_ligne()["regles"] == "rafale"
    for invalide in [(-1.0, ("a",), ("m",)), (1.0, ("a", "b"), ("m",)), (1.0, (), ())]:
        with pytest.raises(ParametreInvalide):
            Alerte(transaction(1), *invalide)
    assert ResultatRegle("r", False).poids == 0


# --- Configuration -----------------------------------------------------------------------------


def test_configuration_retenue_chargee_et_identique_a_l_integree() -> None:
    configuration = charger_configuration(CONFIG_RETENUE)
    assert configuration == configuration_par_defaut()
    moteur = configuration.construire_moteur()
    assert len(moteur) >= 5 and moteur.seuil_alerte == configuration.seuil_alerte
    assert "montant_significatif" in moteur and "montant_eleve" in moteur


def test_configuration_aller_retour(tmp_path: Path) -> None:
    configuration = configuration_par_defaut()
    chemin = enregistrer_configuration(configuration, tmp_path / "c.json")
    assert charger_configuration(chemin) == configuration
    modifiee = configuration.avec(
        seuil_alerte=3, rafale__poids=4, rafale__nb_operations=5, montant_eleve__active=False
    )
    moteur = modifiee.construire_moteur()
    assert moteur.seuil_alerte == 3 and "montant_eleve" not in moteur
    assert next(r for r in moteur if r.nom == "rafale").parametres()["nb_operations"] == 5
    with pytest.raises(ConfigurationInvalide):
        configuration.avec(regle_absente__poids=1)


def _ecrire(tmp_path: Path, contenu: object) -> Path:
    chemin = tmp_path / "config.json"
    chemin.write_text(
        contenu if isinstance(contenu, str) else json.dumps(contenu), encoding="utf-8"
    )
    return chemin


REGLE_OK = {"nom": "rafale", "poids": 2, "parametres": {"nb_operations": 3}}


@pytest.mark.parametrize(
    "contenu, message",
    [
        ("{ pas du json", "JSON invalide"),
        ([], "racine"),
        ({"regles": [REGLE_OK]}, "seuil_alerte"),
        ({"seuil_alerte": -1, "regles": [REGLE_OK]}, "seuil_alerte"),
        ({"seuil_alerte": "2", "regles": [REGLE_OK]}, "seuil_alerte"),
        ({"seuil_alerte": 2, "regles": []}, "liste non vide"),
        ({"seuil_alerte": 2, "regles": [REGLE_OK], "seuil": 3}, "clé"),
        ({"seuil_alerte": 2, "regles": [{**REGLE_OK, "nom": "inconnue"}]}, "inconnue"),
        ({"seuil_alerte": 2, "regles": [{**REGLE_OK, "poids": -1}]}, "poids"),
        ({"seuil_alerte": 2, "regles": [{**REGLE_OK, "active": "oui"}]}, "active"),
        (
            {"seuil_alerte": 2, "regles": [{**REGLE_OK, "parametres": {"nb_operations": 0}}]},
            "nb_operations",
        ),
        ({"seuil_alerte": 2, "regles": [{**REGLE_OK, "parametres": {"fenetre": 3}}]}, "paramètre"),
        ({"seuil_alerte": 2, "regles": [{**REGLE_OK, "parametres": []}]}, "parametres"),
        ({"seuil_alerte": 2, "regles": [REGLE_OK, REGLE_OK]}, "deux fois"),
        ({"seuil_alerte": 2, "regles": [{**REGLE_OK, "active": False}]}, "aucune règle active"),
        ({"seuil_alerte": 2, "regles": ["rafale"]}, "objet"),
        ({"seuil_alerte": 2, "regles": [{**REGLE_OK, "identifiant": 3}]}, "identifiant"),
    ],
)
def test_configuration_invalide(tmp_path: Path, contenu: object, message: str) -> None:
    with pytest.raises(ConfigurationInvalide, match=message):
        charger_configuration(_ecrire(tmp_path, contenu))


def test_configuration_fichier_absent(tmp_path: Path) -> None:
    with pytest.raises(ConfigurationInvalide, match="introuvable"):
        charger_configuration(tmp_path / "absent.json")


def test_configuration_identifiants_distincts_pour_reutiliser_une_regle() -> None:
    configuration = ConfigurationMoteur.depuis_dict(
        {
            "seuil_alerte": 2,
            "regles": [
                {
                    "nom": "montant_eleve",
                    "identifiant": "palier_bas",
                    "parametres": {"seuil": 50_000},
                },
                {"nom": "montant_eleve", "parametres": {"seuil": 150_000}},
            ],
        }
    )
    moteur = configuration.construire_moteur()
    assert moteur.evaluer(transaction(montant=200_000)).score == 2
    assert moteur.evaluer(transaction(montant=60_000)).regles == ("palier_bas",)


# --- Évaluation ---------------------------------------------------------------------------------


def _jeu_etiquete() -> list:
    return [
        transaction(1, montant=1_000_000, fraude=True),
        transaction(2, montant=200_000, fraude=True),
        transaction(3, fraude=False),
        transaction(4, fraude=False),
        transaction(5, fraude=False),
    ]


def test_matrice_de_confusion_et_cout_metier() -> None:
    rapport = evaluer(_jeu_etiquete(), {"T00001", "T00003"}, nom="test")
    m = rapport.matrice
    assert (m.fraudes_detectees, m.fraudes_manquees, m.fausses_alertes, m.vrais_negatifs) == (
        1,
        1,
        1,
        2,
    )
    assert (
        m.taux_detection == 0.5
        and m.precision == 0.5
        and m.taux_fausses_alertes == pytest.approx(1 / 3)
    )
    assert m.exactitude == 0.6 and m.f1 == 0.5 and m.taux_alerte == 0.4
    assert rapport.cout_fraudes_manquees == 200_000 and rapport.cout_fausses_alertes == 500
    assert rapport.cout_total == 200_500 and rapport.montant_fraudes_detectees == 1_000_000
    assert rapport.vers_dict()["cout_total"] == 200_500


def test_exactitude_trompeuse_et_references() -> None:
    aucune, tout = references(_jeu_etiquete())
    assert aucune.matrice.taux_detection == 0 and aucune.cout_total == 1_200_000
    assert tout.matrice.taux_detection == 1 and tout.cout_total == 3 * 500
    # « Ne rien signaler » a une meilleure exactitude que « tout signaler »,
    # et pourtant coûte 800 fois plus.
    assert aucune.matrice.exactitude > tout.matrice.exactitude


def test_evaluation_exige_les_etiquettes() -> None:
    with pytest.raises(DonneesInvalides):
        evaluer([transaction(1, fraude=None)], set())
    with pytest.raises(ParametreInvalide):
        evaluer([], set(), cout_fausse_alerte=-1)
    vide = evaluer([], set())
    assert vide.matrice.taux_detection == 0 and vide.cout_relatif == 0


def test_seuils_scenarios_contributions_et_mois(csv_simule: Path) -> None:
    import csv

    transactions = sorted(lire_transactions(csv_simule))
    configuration = charger_configuration(CONFIG_RETENUE)
    evaluations = list(configuration.construire_moteur().analyser(transactions))
    rapports = evaluer_seuils(evaluations, [1, 2, 3, 4])
    alertes = [r.matrice.nb_alertes for r in rapports]
    assert alertes == sorted(alertes, reverse=True), "relever le seuil réduit le nombre d'alertes"
    retenu = rapports[1]
    assert (
        retenu.cout_total < references(transactions)[0].cout_total
    ), "le moteur fait mieux que l'absence de détection"
    assert retenu.matrice.taux_detection > 0.8

    with (csv_simule.parent / "scenarios.csv").open(encoding="utf-8") as fichier:
        scenarios = {
            ligne["id_transaction"]: ligne["scenario"] for ligne in csv.DictReader(fichier)
        }
    signales = {e.transaction.id_transaction for e in evaluations if e.est_alerte(2)}
    par_scenario = detection_par_scenario(evaluations, signales, scenarios)
    assert sum(v["fraudes"] for v in par_scenario.values()) == retenu.matrice.nb_fraudes
    contributions = contribution_des_regles(evaluations, 2)
    assert contributions and all(
        v["sur_fraudes"] + v["sur_legitimes"] > 0 for v in contributions.values()
    )
    mois = evolution_mensuelle(evaluations, 2)
    assert len(mois) == 6 and sum(r.cout_total for r in mois) == retenu.cout_total
