"""Interface en ligne de commande de PayGuard (``payguard <commande> ...``).

Sous-commandes :

* ``generer``  — phase 1 : CSV synthétique brut (bibliothèque standard) ;
* ``simuler``  — phase 2 : mêmes opérations exécutées par la plateforme
  (règles métier), CSV des transactions acceptées + base SQLite ;
* ``analyser`` — phase 4 : analyse exploratoire, figures, comparaison des
  profils Python pur / pandas ;
* ``detecter`` — phase 5 : moteur de règles sur un CSV (étiqueté ou non),
  affichage des règles déclenchées pour chaque alerte, CSV des alertes ;
* ``evaluer``  — phase 5 : métriques, coût métier, comparaison de réglages.

Codes de sortie : 0 succès, 1 erreur métier (message explicite), 2 erreur
d'arguments (argparse), 130 interruption clavier.
"""

from __future__ import annotations

import argparse
import csv
import json
import logging
import sys
from collections.abc import Sequence
from datetime import date
from pathlib import Path
from typing import Any

from payguard import __version__
from payguard.exceptions import PayGuardError
from payguard.journal import configurer_journalisation

journal = logging.getLogger("payguard.cli")

CONFIG_PAR_DEFAUT = Path("config/regles.json")
CSV_SIMULE = Path("data/processed/transactions.csv")
SCENARIOS_SIMULES = Path("data/processed/scenarios.csv")


# --------------------------------------------------------------------------
# Validation des arguments
# --------------------------------------------------------------------------


def _date(texte: str) -> date:
    try:
        return date.fromisoformat(texte)
    except ValueError:
        raise argparse.ArgumentTypeError(
            f"date invalide {texte!r} (format attendu : AAAA-MM-JJ)"
        ) from None


def _entier_positif(texte: str) -> int:
    try:
        valeur = int(texte)
    except ValueError:
        raise argparse.ArgumentTypeError(f"entier attendu (reçu : {texte!r})") from None
    if valeur <= 0:
        raise argparse.ArgumentTypeError(f"entier strictement positif attendu (reçu : {valeur})")
    return valeur


def _entier_positif_ou_nul(texte: str) -> int:
    try:
        valeur = int(texte)
    except ValueError:
        raise argparse.ArgumentTypeError(f"entier attendu (reçu : {texte!r})") from None
    if valeur < 0:
        raise argparse.ArgumentTypeError(f"entier positif ou nul attendu (reçu : {valeur})")
    return valeur


def _taux(texte: str) -> float:
    try:
        valeur = float(texte)
    except ValueError:
        raise argparse.ArgumentTypeError(f"nombre attendu (reçu : {texte!r})") from None
    if not 0.0 <= valeur <= 0.2:
        raise argparse.ArgumentTypeError(
            f"le taux doit être compris entre 0 et 0.2 (reçu : {valeur})"
        )
    return valeur


def _reel_positif(texte: str) -> float:
    try:
        valeur = float(texte)
    except ValueError:
        raise argparse.ArgumentTypeError(f"nombre attendu (reçu : {texte!r})") from None
    if valeur <= 0:
        raise argparse.ArgumentTypeError(f"nombre strictement positif attendu (reçu : {valeur})")
    return valeur


def _fichier_existant(texte: str) -> Path:
    chemin = Path(texte)
    if not chemin.is_file():
        raise argparse.ArgumentTypeError(f"fichier introuvable : {texte}")
    return chemin


# --------------------------------------------------------------------------
# Affichage
# --------------------------------------------------------------------------


def _gnf(montant: float) -> str:
    return f"{montant:,.0f}".replace(",", " ") + " GNF"


def _pourcent(valeur: float) -> str:
    return f"{valeur:.2%}"


def _tableau(lignes: list[dict[str, Any]], colonnes: list[tuple[str, str]]) -> str:
    """Tableau texte aligné ; ``colonnes`` = [(clé, en-tête), ...]."""
    cellules = [[str(ligne.get(cle, "")) for cle, _ in colonnes] for ligne in lignes]
    entetes = [entete for _, entete in colonnes]
    largeurs = [
        max(len(e), *(len(c[i]) for c in cellules)) if cellules else len(e)
        for i, e in enumerate(entetes)
    ]
    separateur = "  "
    sortie = [separateur.join(e.ljust(l) for e, l in zip(entetes, largeurs))]
    sortie.append(separateur.join("-" * largeur for largeur in largeurs))
    for ligne in cellules:
        sortie.append(
            separateur.join(
                c.ljust(l) if i == 0 else c.rjust(l)
                for i, (c, l) in enumerate(zip(ligne, largeurs))
            )
        )
    return "\n".join(sortie)


def _afficher(texte: str = "") -> None:
    """Sortie destinée à l'utilisateur (résultats), distincte du journal technique."""
    print(texte)


# --------------------------------------------------------------------------
# Commandes
# --------------------------------------------------------------------------


def _parametres_generation(args: argparse.Namespace) -> dict[str, Any]:
    return {
        "nb_comptes": args.comptes,
        "nb_operations": args.operations,
        "debut": args.debut,
        "fin": args.fin,
        "taux_fraude": args.taux_fraude,
        "graine": args.graine,
    }


def commande_generer(args: argparse.Namespace) -> int:
    """Phase 1 : génère le CSV brut."""
    from payguard.generation.generateur import generer_jeu_de_donnees

    resume = generer_jeu_de_donnees(
        args.sortie, chemin_scenarios=args.scenarios, **_parametres_generation(args)
    )
    _afficher(f"Fichier généré : {args.sortie}")
    _afficher(
        f"  transactions : {resume['nb_transactions']}  |  fraudes : {resume['nb_fraudes']} "
        f"({_pourcent(resume['taux_fraude'])})  |  graine : {resume['graine']}"
    )
    _afficher(
        f"  période : {resume['debut']} -> {resume['fin']}  "
        f"|  comptes actifs : {resume['nb_comptes_actifs']}"
    )
    _afficher(f"  par type : {resume['par_type']}")
    _afficher(f"  par scénario de fraude : {resume['par_scenario']}")
    if args.scenarios:
        _afficher(f"  scénarios des fraudes : {args.scenarios}")
    return 0


def commande_simuler(args: argparse.Namespace) -> int:
    """Phase 2 : exécute les opérations générées sur la plateforme."""
    from payguard.generation.simulation import ecrire_scenarios, ecrire_transactions, simuler

    resultat = simuler(**_parametres_generation(args))
    ecrire_transactions(resultat.transactions, args.sortie)
    ecrire_scenarios(resultat.scenarios, args.scenarios)
    resume = resultat.resume()
    _afficher(f"Simulation terminée ({resultat.plateforme!r})")
    _afficher(
        f"  transactions acceptées : {resume['nb_transactions_acceptees']}  ->  {args.sortie}"
    )
    _afficher(
        "  opérations rejetées par les règles métier : "
        f"{resume['nb_rejets']} {resume['rejets_par_motif']}"
    )
    _afficher(f"  fraudes acceptées : {resume['nb_fraudes']} ({_pourcent(resume['taux_fraude'])})")
    _afficher(f"  frais encaissés par la plateforme : {_gnf(resume['revenus_plateforme'])}")
    if not args.sans_base:
        from payguard.donnees.depot import Depot

        with Depot(args.base) as depot:
            depot.vider()
            depot.inserer_transactions(resultat.transactions)
            depot.inserer_comptes(resultat.plateforme.comptes)
            nb = depot.compter_transactions()
        _afficher(
            f"  base SQLite : {args.base} ({nb} transactions, {len(resultat.plateforme)} comptes)"
        )
    return 0


def commande_analyser(args: argparse.Namespace) -> int:
    """Phase 4 : analyse exploratoire et comparaison Python pur / pandas."""
    from payguard.donnees import analyse

    if args.base:
        from payguard.donnees.depot import Depot

        with Depot(args.base) as depot:
            df = depot.lire_dataframe()
        source = str(args.base)
    else:
        df = analyse.charger_csv(args.entree)
        source = str(args.entree)
    if df.empty:
        raise PayGuardError(f"Aucune transaction dans {source}")
    resultats = analyse.analyser(df, args.figures)

    _afficher(
        f"Analyse de {source} : {resultats['nb_transactions']} transactions, "
        f"taux de fraude {_pourcent(resultats['taux_fraude_global'])}"
    )
    _afficher("\n[1] Montants par type (GNF)")
    _afficher(
        resultats["montants_par_type"][["count", "25%", "50%", "75%", "99%"]].round(0).to_string()
    )
    heures = resultats["fraude_par_heure"]
    nuit, jour = heures.loc[0:4], heures.loc[5:23]
    taux_nuit = nuit["fraudes"].sum() / nuit["transactions"].sum()
    taux_jour = jour["fraudes"].sum() / jour["transactions"].sum()
    _afficher(
        f"\n[2] Taux de fraude 0 h-5 h : {_pourcent(taux_nuit)} "
        f"contre {_pourcent(taux_jour)} le reste de la journée"
    )
    _afficher(resultats["fraude_par_zone"].to_string(formatters={"taux_fraude": _pourcent}))
    concentration = resultats["concentration"]
    _afficher(
        "\n[3] Le 1 % de comptes le plus actif "
        f"({concentration['nb_comptes_retenus']} comptes) porte "
        f"{_pourcent(concentration['part_volume_plus_actifs'])} du volume émis "
        f"(types : {concentration['types_comptes_plus_actifs']})"
    )
    _afficher("\n[4] Délai depuis la transaction précédente du même émetteur (minutes)")
    _afficher(resultats["delai_median"].round(1).to_string())
    _afficher("\n[5] Fraude et ancienneté de l'émetteur")
    _afficher(resultats["fraude_par_anciennete"].to_string(formatters={"taux_fraude": _pourcent}))
    _afficher("\n[6] Fraude et appareil (question libre)")
    _afficher(
        resultats["fraude_nouvel_appareil"].to_string(
            formatters={"taux_fraude": _pourcent, "part_des_fraudes": _pourcent}
        )
    )
    if args.figures:
        _afficher(f"\nFigures : {', '.join(resultats['figures'])}")

    if args.benchmark:
        from payguard.donnees.profils import comparer_implementations
        from payguard.outils.flux import lire_transactions

        if args.base:
            with Depot(args.base) as depot:
                transactions = list(depot.transactions())
        else:
            transactions = list(lire_transactions(args.entree))
        mesure = comparer_implementations(transactions, df, repetitions=args.repetitions)
        _afficher(
            f"\n[Profils] Python pur vs pandas sur {mesure['nb_transactions']} transactions "
            f"({mesure['nb_comptes']} comptes, meilleur de {mesure['repetitions']} essais)"
        )
        _afficher(f"  résultats identiques : {'oui' if mesure['identiques'] else 'NON'}")
        _afficher(
            f"  Python pur : {mesure['python_s']:.3f} s  |  pandas (agrégation) : "
            f"{mesure['pandas_agregation_s']:.3f} s  |  pandas (complet) : "
            f"{mesure['pandas_complet_s']:.3f} s"
        )
        _afficher(
            f"  accélération pandas : x{mesure['acceleration_agregation']:.1f} (agrégation), "
            f"x{mesure['acceleration_complet']:.1f} (complet)"
        )
        if not mesure["identiques"]:
            return 1
    return 0


def _charger_config(chemin: Path | None) -> tuple[Any, str]:
    from payguard.detection.configuration import charger_configuration, configuration_par_defaut

    if chemin is not None:
        return charger_configuration(chemin), str(chemin)
    if CONFIG_PAR_DEFAUT.is_file():
        return charger_configuration(CONFIG_PAR_DEFAUT), str(CONFIG_PAR_DEFAUT)
    return configuration_par_defaut(), "configuration intégrée"


def commande_detecter(args: argparse.Namespace) -> int:
    """Phase 5 : détection sur un fichier (étiqueté ou non)."""
    from payguard.detection.alerte import COLONNES_ALERTES, Alerte
    from payguard.outils.flux import RapportLecture, lire_transactions

    configuration, origine = _charger_config(args.config)
    moteur = configuration.construire_moteur()
    profils = None
    if args.historique:
        from payguard.donnees.profils import ProfilsComptes

        profils = ProfilsComptes.calculer_python(lire_transactions(args.historique))
        _afficher(f"Historique de référence : {args.historique} ({len(profils)} comptes)")

    rapport = RapportLecture()
    flux = lire_transactions(args.entree, strict=args.strict, rapport=rapport)
    if not args.flux:
        flux = iter(sorted(flux))  # le moteur exige l'ordre chronologique
    _afficher(f"Détection sur {args.entree} — {moteur!r} ({origine})")

    args.sortie.parent.mkdir(parents=True, exist_ok=True)
    nb_transactions = nb_alertes = 0
    vp = fp = fn = 0
    cout_manque = 0
    par_regle: dict[str, int] = {}
    alertes_conservees: list[Alerte] = []
    with args.sortie.open("w", newline="", encoding="utf-8") as fichier:
        ecrivain = csv.DictWriter(fichier, fieldnames=COLONNES_ALERTES)
        ecrivain.writeheader()
        for evaluation in moteur.analyser(flux, profils):
            nb_transactions += 1
            signalee = evaluation.est_alerte(moteur.seuil_alerte)
            etiquette = evaluation.transaction.est_fraude
            if etiquette is not None:
                if etiquette and signalee:
                    vp += 1
                elif etiquette:
                    fn += 1
                    cout_manque += evaluation.transaction.montant
                elif signalee:
                    fp += 1
            if not signalee:
                continue
            alerte = Alerte.depuis_evaluation(evaluation)
            nb_alertes += 1
            ecrivain.writerow(alerte.vers_ligne())
            for regle in alerte.regles:
                par_regle[regle] = par_regle.get(regle, 0) + 1
            if args.base:
                alertes_conservees.append(alerte)
            if args.limite is None or nb_alertes <= args.limite:
                if args.details:
                    _afficher(str(alerte))
                else:
                    _afficher(
                        f"{alerte.id_transaction}  score {alerte.score:g}  "
                        f"{_gnf(alerte.transaction.montant):>16}"
                        f"  règles : {', '.join(alerte.regles)}"
                    )

    if args.limite is not None and nb_alertes > args.limite:
        _afficher(f"... {nb_alertes - args.limite} autres alertes (toutes dans {args.sortie})")
    _afficher("")
    _afficher(
        f"Transactions analysées : {nb_transactions}  | "
        f" lignes ignorées : {rapport.lignes_rejetees}"
    )
    _afficher(
        f"Alertes : {nb_alertes} "
        f"({_pourcent(nb_alertes / nb_transactions if nb_transactions else 0)})"
        f"  ->  {args.sortie}"
    )
    if par_regle:
        _afficher(
            "Déclenchements par règle (parmi les alertes) : "
            + ", ".join(f"{r}={n}" for r, n in sorted(par_regle.items(), key=lambda x: -x[1]))
        )
    if rapport.erreurs:
        _afficher(f"Premières lignes ignorées : {rapport.erreurs[:5]}")
    if rapport.etiquette_presente and vp + fn:
        cout = cout_manque + 500 * fp
        _afficher(
            "Étiquettes présentes (non utilisées par le "
            f"moteur) : {vp} fraudes détectées, {fn} manquées, "
            f"{fp} fausses alertes, coût métier {_gnf(cout)}"
        )
    else:
        _afficher(
            "Fichier sans étiquette : utilisez « payguard evaluer "
            "» sur un fichier étiqueté pour mesurer le coût."
        )
    if args.base:
        from payguard.donnees.depot import Depot

        with Depot(args.base) as depot:
            depot.inserer_alertes(alertes_conservees)
        _afficher(f"Alertes enregistrées dans {args.base}")
    return 0


def _ligne_rapport(rapport: Any) -> dict[str, Any]:
    d = rapport.vers_dict()
    return {
        "reglage": d["reglage"],
        "alertes": d["alertes"],
        "detectees": d["fraudes_detectees"],
        "manquees": d["fraudes_manquees"],
        "fausses": d["fausses_alertes"],
        "detection": _pourcent(d["taux_detection"]),
        "precision": _pourcent(d["precision"]),
        "exactitude": _pourcent(d["exactitude"]),
        "cout": _gnf(d["cout_total"]),
    }


_COLONNES_RAPPORT = [
    ("reglage", "Réglage"),
    ("alertes", "Alertes"),
    ("detectees", "Détectées"),
    ("manquees", "Manquées"),
    ("fausses", "Fausses alertes"),
    ("detection", "Taux détection"),
    ("precision", "Précision"),
    ("exactitude", "Exactitude"),
    ("cout", "Coût métier"),
]


def commande_evaluer(args: argparse.Namespace) -> int:
    """Phase 5 : évaluation, coût métier et comparaison de réglages."""
    from payguard.detection.evaluation import (
        contribution_des_regles,
        detection_par_scenario,
        evaluer,
        evaluer_seuils,
        evolution_mensuelle,
        references,
    )
    from payguard.exceptions import DonneesInvalides
    from payguard.outils.flux import RapportLecture, lire_transactions

    rapport_lecture = RapportLecture()
    transactions = sorted(lire_transactions(args.entree, rapport=rapport_lecture))
    if not rapport_lecture.etiquette_presente or any(t.est_fraude is None for t in transactions):
        raise DonneesInvalides(
            f"{args.entree} : la colonne est_fraude est nécessaire pour évaluer"
        )
    configs = args.config or [None]
    rapports = list(references(transactions))
    evaluations_retenues = None
    configuration_retenue = None
    for chemin in configs:
        configuration, origine = _charger_config(chemin)
        moteur = configuration.construire_moteur()
        evaluations = list(moteur.analyser(transactions))
        signales = {
            e.transaction.id_transaction for e in evaluations if e.est_alerte(moteur.seuil_alerte)
        }
        nom = (
            origine
            if chemin is None and origine == "configuration intégrée"
            else Path(origine).stem
        )
        rapports.append(evaluer(evaluations, signales, nom=nom))
        if evaluations_retenues is None:
            evaluations_retenues, configuration_retenue = evaluations, configuration
        if args.seuils and chemin is configs[0]:
            rapports.extend(evaluer_seuils(evaluations, args.seuils, prefixe=f"{nom} / seuil"))

    _afficher(
        f"Évaluation sur {args.entree} : {len(transactions)} transactions, "
        f"{sum(1 for t in transactions if t.est_fraude)} fraudes"
    )
    _afficher(_tableau([_ligne_rapport(r) for r in rapports], _COLONNES_RAPPORT))
    candidats = [r for r in rapports if not r.nom.startswith("référence")]
    meilleur = min(candidats, key=lambda r: r.cout_total)
    _afficher(
        f"\nCoût minimal : « {meilleur.nom} » ({_gnf(meilleur.cout_total)}, "
        f"soit {_pourcent(meilleur.cout_relatif)} du coût sans détection)"
    )
    _afficher(
        "Rappel : l'exactitude d'un moteur qui ne signale rien serait de "
        f"{_pourcent(rapports[0].matrice.exactitude)} — elle ne mesure pas la détection."
    )

    assert evaluations_retenues is not None and configuration_retenue is not None
    seuil = configuration_retenue.seuil_alerte
    signales = {e.transaction.id_transaction for e in evaluations_retenues if e.est_alerte(seuil)}
    _afficher("\nContribution des règles (premier réglage, parmi les alertes) :")
    _afficher(
        _tableau(
            [
                {"regle": r, **v}
                for r, v in contribution_des_regles(evaluations_retenues, seuil).items()
            ],
            [
                ("regle", "Règle"),
                ("sur_fraudes", "Sur fraudes"),
                ("sur_legitimes", "Sur légitimes"),
            ],
        )
    )
    if args.scenarios:
        with Path(args.scenarios).open(encoding="utf-8") as fichier:
            scenarios = {
                ligne["id_transaction"]: ligne["scenario"] for ligne in csv.DictReader(fichier)
            }
        par_scenario = detection_par_scenario(evaluations_retenues, signales, scenarios)
        _afficher("\nDétection par scénario de fraude (premier réglage) :")
        _afficher(
            _tableau(
                [
                    {
                        "scenario": s,
                        "fraudes": v["fraudes"],
                        "detectees": v["detectees"],
                        "taux": _pourcent(v["taux_detection"]),
                        "manque": _gnf(v["montant_manque"]),
                    }
                    for s, v in par_scenario.items()
                ],
                [
                    ("scenario", "Scénario"),
                    ("fraudes", "Fraudes"),
                    ("detectees", "Détectées"),
                    ("taux", "Taux"),
                    ("manque", "Montant manqué"),
                ],
            )
        )
    if args.mensuel:
        _afficher("\nÉvolution mensuelle (premier réglage) :")
        _afficher(
            _tableau(
                [_ligne_rapport(r) for r in evolution_mensuelle(evaluations_retenues, seuil)],
                _COLONNES_RAPPORT,
            )
        )
    if args.json:
        args.json.parent.mkdir(parents=True, exist_ok=True)
        args.json.write_text(
            json.dumps([r.vers_dict() for r in rapports], indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
        _afficher(f"\nRapport JSON : {args.json}")
    return 0


# --------------------------------------------------------------------------
# Analyseur d'arguments
# --------------------------------------------------------------------------


def _ajouter_options_generation(parser: argparse.ArgumentParser) -> None:
    from payguard.generation import generateur as gen

    groupe = parser.add_argument_group("paramètres de génération")
    groupe.add_argument(
        "--comptes",
        type=_entier_positif,
        default=gen.NB_COMPTES_DEFAUT,
        help="nombre de comptes (défaut : %(default)s)",
    )
    groupe.add_argument(
        "--operations",
        type=_entier_positif,
        default=gen.NB_OPERATIONS_DEFAUT,
        help="opérations légitimes tirées, hors réapprovisionnements "
        "et fraudes (défaut : %(default)s)",
    )
    groupe.add_argument(
        "--debut",
        type=_date,
        default=gen.DEBUT_DEFAUT,
        help="premier jour, AAAA-MM-JJ (défaut : %(default)s)",
    )
    groupe.add_argument(
        "--fin",
        type=_date,
        default=gen.FIN_DEFAUT,
        help="jour de fin exclu, AAAA-MM-JJ (défaut : %(default)s)",
    )
    groupe.add_argument(
        "--taux-fraude",
        type=_taux,
        default=gen.TAUX_FRAUDE_DEFAUT,
        help="part visée de fraudes, entre 0 et 0.2 (défaut : %(default)s)",
    )
    groupe.add_argument(
        "--graine",
        type=int,
        default=gen.GRAINE_DEFAUT,
        help="graine aléatoire, pour la reproductibilité (défaut : %(default)s)",
    )


def construire_parser() -> argparse.ArgumentParser:
    """Construit l'analyseur d'arguments et ses sous-commandes."""
    parser = argparse.ArgumentParser(
        prog="payguard",
        description="PayGuard : simulation de paiement mobile "
        "(GNF) et détection de fraude par règles.",
        epilog="Exemple : payguard simuler && payguard detecter data/processed/transactions.csv",
    )
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    parser.add_argument(
        "--journal",
        type=Path,
        default=Path("data/payguard.log"),
        help="fichier de journal (défaut : %(default)s)",
    )
    parser.add_argument(
        "-v", "--verbeux", action="store_true", help="journal détaillé (niveau DEBUG)"
    )
    sous = parser.add_subparsers(dest="commande", required=True, metavar="commande")

    p = sous.add_parser(
        "generer",
        help="phase 1 : générer un CSV synthétique brut",
        description="Génère un CSV de transactions synthétiques "
        "(annexe A), sans passer par la plateforme.",
    )
    _ajouter_options_generation(p)
    p.add_argument(
        "-o",
        "--sortie",
        type=Path,
        default=Path("data/raw/transactions.csv"),
        help="CSV produit (défaut : %(default)s)",
    )
    p.add_argument(
        "--scenarios",
        type=Path,
        default=Path("data/raw/scenarios.csv"),
        help="fichier annexe id_transaction,scenario des fraudes (défaut : %(default)s)",
    )
    p.set_defaults(fonction=commande_generer)

    p = sous.add_parser(
        "simuler",
        help="phase 2 : exécuter les opérations sur la plateforme",
        description="Génère les comptes et opérations puis les exécute sur la plateforme "
        "(soldes, plafonds, frais) ; seules les transactions acceptées sont conservées.",
    )
    _ajouter_options_generation(p)
    p.add_argument(
        "-o",
        "--sortie",
        type=Path,
        default=CSV_SIMULE,
        help="CSV des transactions acceptées (défaut : %(default)s)",
    )
    p.add_argument(
        "--scenarios",
        type=Path,
        default=SCENARIOS_SIMULES,
        help="fichier annexe des scénarios de fraude (défaut : %(default)s)",
    )
    p.add_argument(
        "--base",
        type=Path,
        default=Path("data/payguard.db"),
        help="base SQLite (défaut : %(default)s)",
    )
    p.add_argument("--sans-base", action="store_true", help="ne pas écrire la base SQLite")
    p.set_defaults(fonction=commande_simuler)

    p = sous.add_parser(
        "analyser",
        help="phase 4 : analyse exploratoire et figures",
        description="Analyse exploratoire (pandas, Matplotlib) et "
        "comparaison des profils Python pur / pandas.",
    )
    source = p.add_mutually_exclusive_group()
    source.add_argument(
        "-i",
        "--entree",
        type=_fichier_existant,
        default=None,
        help=f"CSV étiqueté à analyser (défaut : {CSV_SIMULE})",
    )
    source.add_argument(
        "--base", type=_fichier_existant, help="lire les transactions depuis une base SQLite"
    )
    p.add_argument(
        "--figures",
        type=Path,
        default=Path("rapport/figures"),
        help="dossier des figures (défaut : %(default)s)",
    )
    p.add_argument(
        "--benchmark",
        action="store_true",
        help="comparer et chronométrer les profils Python pur / pandas",
    )
    p.add_argument(
        "--repetitions",
        type=_entier_positif,
        default=3,
        help="répétitions du benchmark (défaut : %(default)s)",
    )
    p.set_defaults(fonction=commande_analyser)

    p = sous.add_parser(
        "detecter",
        help="phase 5 : détecter les transactions suspectes",
        description="Applique le moteur de règles à un CSV (avec "
        "ou sans colonne est_fraude) et affiche, "
        "pour chaque alerte, les règles qui l'ont déclenchée.",
    )
    p.add_argument(
        "entree",
        type=_fichier_existant,
        help="CSV de transactions (annexe A ; est_fraude facultative)",
    )
    p.add_argument(
        "-c",
        "--config",
        type=_fichier_existant,
        default=None,
        help="configuration JSON du moteur (défaut : "
        f"{CONFIG_PAR_DEFAUT}, sinon configuration intégrée)",
    )
    p.add_argument(
        "-o",
        "--sortie",
        type=Path,
        default=Path("data/processed/alertes.csv"),
        help="CSV des alertes (défaut : %(default)s)",
    )
    p.add_argument(
        "--historique",
        type=_fichier_existant,
        default=None,
        help="CSV d'historique servant à initialiser les profils (facultatif)",
    )
    p.add_argument(
        "--details",
        action="store_true",
        help="afficher le motif détaillé de chaque règle déclenchée",
    )
    p.add_argument(
        "--limite",
        type=_entier_positif_ou_nul,
        default=None,
        help="n'afficher que les N premières alertes (toutes sont écrites dans le CSV)",
    )
    p.add_argument(
        "--flux",
        action="store_true",
        help="traitement au fil de l'eau, sans charger le "
        "fichier (il doit être trié par horodatage)",
    )
    p.add_argument(
        "--strict",
        action="store_true",
        help="échouer à la première ligne invalide au lieu de l'ignorer",
    )
    p.add_argument(
        "--base",
        type=Path,
        default=None,
        help="enregistrer aussi les alertes dans cette base SQLite",
    )
    p.set_defaults(fonction=commande_detecter)

    p = sous.add_parser(
        "evaluer",
        help="phase 5 : mesurer le moteur et son coût métier",
        description="Compare les alertes aux étiquettes : détections, "
        "manques, fausses alertes, coût métier "
        "(fraude manquée = son montant, fausse alerte = 500 GNF).",
    )
    p.add_argument(
        "-i",
        "--entree",
        type=_fichier_existant,
        default=None,
        help=f"CSV étiqueté (défaut : {CSV_SIMULE})",
    )
    p.add_argument(
        "-c",
        "--config",
        type=_fichier_existant,
        nargs="+",
        default=None,
        help="une ou plusieurs configurations JSON à comparer",
    )
    p.add_argument(
        "--seuils",
        type=_reel_positif,
        nargs="+",
        default=None,
        help="seuils d'alerte supplémentaires à évaluer avec la première configuration",
    )
    p.add_argument(
        "--scenarios",
        type=_fichier_existant,
        default=None,
        help="fichier annexe des scénarios, pour le taux de détection par scénario",
    )
    p.add_argument(
        "--mensuel", action="store_true", help="afficher l'évolution du coût mois par mois"
    )
    p.add_argument("--json", type=Path, default=None, help="enregistrer les résultats en JSON")
    p.set_defaults(fonction=commande_evaluer)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    """Point d'entrée de la commande ``payguard``."""
    parser = construire_parser()
    args = parser.parse_args(argv)
    if getattr(args, "entree", "absent") is None and not (
        args.commande == "analyser" and args.base
    ):
        if not CSV_SIMULE.is_file():
            parser.error(
                "aucun fichier d'entrée : lancez d'abord « payguard simuler » ou passez --entree"
            )
        args.entree = CSV_SIMULE
    configurer_journalisation(
        logging.DEBUG if args.verbeux else logging.INFO,
        fichier=args.journal,
        niveau_console=logging.WARNING,
        exclus_console=("payguard.cli",),
    )
    journal.info("Commande : %s", " ".join(sys.argv[1:] if argv is None else argv))
    try:
        return int(args.fonction(args))
    except PayGuardError as erreur:
        journal.error("%s", erreur)
        print(f"Erreur : {erreur}", file=sys.stderr)
        return 1
    except OSError as erreur:
        journal.error("Erreur de fichier : %s", erreur)
        print(f"Erreur de fichier : {erreur}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print("Interrompu.", file=sys.stderr)
        return 130


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
