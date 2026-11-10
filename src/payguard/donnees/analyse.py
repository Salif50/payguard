"""Analyse exploratoire des transactions avec pandas et Matplotlib (phase 4).

Chaque question du sujet est traitée par une fonction ``calculer_*`` (qui
renvoie un résultat chiffré : DataFrame, Series ou nombre) et, le cas
échéant, une fonction ``tracer_*`` (qui produit une figure). Séparer calcul
et tracé permet de tester les calculs sans rien afficher et de réutiliser
les résultats dans le notebook et le rapport.

Questions traitées (six, pour cinq exigées) :

1. distribution des montants par type (échelle logarithmique) ;
2. taux de fraude par tranche horaire et par zone ;
3. part du volume total portée par le centile de comptes le plus actif ;
4. délai médian entre deux transactions successives, fraude ou non ;
5. lien entre ancienneté du compte et fraude ;
6. question libre : la fraude est-elle plus fréquente depuis un appareil
   jamais vu pour le compte ? (elle justifie la règle « nouvel appareil »).
"""

from __future__ import annotations

import logging
import math
import sys
from pathlib import Path
from typing import Any

import matplotlib

if "ipykernel" not in sys.modules:
    # Rendu sans fenêtre (CLI, tests, serveur) ; dans un notebook, on garde
    # le moteur « inline » de Jupyter pour afficher les figures.
    matplotlib.use("Agg")

import matplotlib.pyplot as plt  # noqa: E402
import pandas as pd  # noqa: E402
from matplotlib.figure import Figure  # noqa: E402
from matplotlib.ticker import FuncFormatter, PercentFormatter  # noqa: E402

from payguard.exceptions import DonneesInvalides  # noqa: E402
from payguard.schema import COLONNES_OBLIGATOIRES, TYPES_OPERATIONS  # noqa: E402

journal = logging.getLogger(__name__)

# Palette (références de la charte : surface claire, encres, deux teintes catégorielles).
SURFACE = "#fcfcfb"
ENCRE = "#0b0b0b"
ENCRE_SECONDAIRE = "#52514e"
ENCRE_DISCRETE = "#898781"
GRILLE = "#e1e0d9"
AXE = "#c3c2b7"
BLEU = "#2a78d6"  # série unique / transactions légitimes
ORANGE = "#eb6834"  # transactions frauduleuses

LIBELLES_TYPES = {
    "depot": "Dépôt",
    "retrait": "Retrait",
    "transfert": "Transfert",
    "paiement_marchand": "Paiement marchand",
}
TRANCHES_ANCIENNETE = [
    (0, 1, "< 1 jour"),
    (1, 7, "1 à 7 jours"),
    (7, 30, "7 à 30 jours"),
    (30, 90, "30 à 90 jours"),
    (90, 100_000, "> 90 jours"),
]


# --------------------------------------------------------------------------
# Chargement
# --------------------------------------------------------------------------


def charger_csv(chemin: str | Path) -> pd.DataFrame:
    """Charge un CSV au format de l'annexe A dans un DataFrame typé.

    ``horodatage`` devient ``datetime64``, ``montant`` un entier ;
    ``est_fraude`` (si présente) un entier 0/1.

    Raises:
        DonneesInvalides: fichier absent ou colonnes obligatoires manquantes.
    """
    chemin = Path(chemin)
    if not chemin.is_file():
        raise DonneesInvalides(f"Fichier introuvable : {chemin}")
    df = pd.read_csv(
        chemin, encoding="utf-8-sig", dtype={"id_emetteur": str, "id_destinataire": str}
    )
    df.columns = [c.strip() for c in df.columns]
    manquantes = [c for c in COLONNES_OBLIGATOIRES if c not in df.columns]
    if manquantes:
        raise DonneesInvalides(f"Colonnes manquantes : {', '.join(manquantes)}")
    df["horodatage"] = pd.to_datetime(df["horodatage"], format="ISO8601")
    df["montant"] = df["montant"].astype("int64")
    if "est_fraude" in df.columns:
        df["est_fraude"] = df["est_fraude"].astype("int64")
    return df


def _exiger_etiquette(df: pd.DataFrame) -> None:
    if "est_fraude" not in df.columns or df["est_fraude"].isna().all():
        raise DonneesInvalides("Cette analyse nécessite la colonne est_fraude")


# --------------------------------------------------------------------------
# Mise en forme commune des figures
# --------------------------------------------------------------------------


def _style_axes(ax: plt.Axes, grille: str = "y") -> None:
    """Axes discrets : fond clair, grille fine, pas de cadre haut/droite."""
    ax.set_facecolor(SURFACE)
    for cote in ("top", "right"):
        ax.spines[cote].set_visible(False)
    for cote in ("left", "bottom"):
        ax.spines[cote].set_color(AXE)
    ax.tick_params(colors=ENCRE_SECONDAIRE, labelsize=9)
    ax.xaxis.label.set_color(ENCRE_SECONDAIRE)
    ax.yaxis.label.set_color(ENCRE_SECONDAIRE)
    ax.title.set_color(ENCRE)
    if grille:
        ax.grid(axis=grille, color=GRILLE, linewidth=0.8)
        ax.set_axisbelow(True)


def _nouvelle_figure(
    largeur: float = 8.0, hauteur: float = 4.5, **kwargs: Any
) -> tuple[Figure, Any]:
    figure, axes = plt.subplots(figsize=(largeur, hauteur), facecolor=SURFACE, **kwargs)
    return figure, axes


def _format_gnf(valeur: float, _position: int | None = None) -> str:
    if valeur >= 1_000_000:
        return f"{valeur / 1_000_000:g} M"
    if valeur >= 1_000:
        return f"{valeur / 1_000:g} k"
    return f"{valeur:g}"


def enregistrer_figure(figure: Figure, chemin: str | Path) -> Path:
    """Enregistre la figure en PNG (150 dpi) et la ferme."""
    chemin = Path(chemin)
    chemin.parent.mkdir(parents=True, exist_ok=True)
    figure.savefig(chemin, dpi=150, bbox_inches="tight", facecolor=SURFACE)
    plt.close(figure)
    return chemin


# --------------------------------------------------------------------------
# Q1 — distribution des montants par type
# --------------------------------------------------------------------------


def calculer_montants_par_type(df: pd.DataFrame) -> pd.DataFrame:
    """Statistiques descriptives des montants (GNF) par type d'opération."""
    stats = df.groupby("type")["montant"].describe(percentiles=[0.25, 0.5, 0.75, 0.99])
    return stats.reindex([t for t in TYPES_OPERATIONS if t in stats.index])


def tracer_montants_par_type(df: pd.DataFrame) -> Figure:
    """Histogrammes des montants par type, abscisse logarithmique (petits multiples)."""
    types = [t for t in TYPES_OPERATIONS if t in set(df["type"])]
    figure, axes = _nouvelle_figure(10, 6, nrows=2, ncols=2, sharex=True)
    # 50 classes régulièrement espacées en échelle logarithmique.
    bas = math.log10(max(1, int(df["montant"].min())))
    haut = math.log10(max(2, int(df["montant"].max())))
    bornes = [10 ** (bas + (haut - bas) * i / 49) for i in range(50)]
    for ax, type_op in zip(axes.flat, types):
        montants = df.loc[df["type"] == type_op, "montant"]
        ax.hist(montants, bins=bornes, color=BLEU, edgecolor=SURFACE, linewidth=0.6)
        ax.axvline(montants.median(), color=ENCRE, linewidth=1, linestyle="--")
        ax.set_xscale("log")
        ax.xaxis.set_major_formatter(FuncFormatter(_format_gnf))
        ax.set_title(
            f"{LIBELLES_TYPES[type_op]} — médiane {_format_gnf(montants.median())} GNF",
            fontsize=10,
            loc="left",
        )
        _style_axes(ax)
    for ax in axes[-1]:
        ax.set_xlabel("Montant (GNF, échelle logarithmique)")
    for ax in axes[:, 0]:
        ax.set_ylabel("Nombre de transactions")
    figure.suptitle(
        "Distribution des montants par type d'opération", color=ENCRE, x=0.01, ha="left"
    )
    figure.tight_layout()
    return figure


# --------------------------------------------------------------------------
# Q2 — taux de fraude par heure et par zone
# --------------------------------------------------------------------------


def calculer_taux_fraude_par_heure(df: pd.DataFrame) -> pd.DataFrame:
    """Nombre de transactions, de fraudes et taux de fraude pour chaque heure (0-23)."""
    _exiger_etiquette(df)
    groupes = df.groupby(df["horodatage"].dt.hour.rename("heure"))["est_fraude"]
    resultat = pd.DataFrame({"transactions": groupes.size(), "fraudes": groupes.sum()})
    resultat = resultat.reindex(range(24), fill_value=0)
    resultat["taux_fraude"] = (resultat["fraudes"] / resultat["transactions"]).fillna(0.0)
    return resultat


def calculer_taux_fraude_par_zone(df: pd.DataFrame) -> pd.DataFrame:
    """Taux de fraude par zone, trié par taux décroissant."""
    _exiger_etiquette(df)
    groupes = df.groupby("zone")["est_fraude"]
    resultat = pd.DataFrame({"transactions": groupes.size(), "fraudes": groupes.sum()})
    resultat["taux_fraude"] = resultat["fraudes"] / resultat["transactions"]
    return resultat.sort_values("taux_fraude", ascending=False)


def tracer_taux_fraude_heure_zone(df: pd.DataFrame) -> Figure:
    """Deux panneaux : taux de fraude par heure (barres) et par zone (barres horizontales)."""
    par_heure = calculer_taux_fraude_par_heure(df)
    par_zone = calculer_taux_fraude_par_zone(df).sort_values("taux_fraude")
    taux_global = df["est_fraude"].mean()
    figure, (ax_h, ax_z) = _nouvelle_figure(
        12, 4.5, ncols=2, gridspec_kw={"width_ratios": [1.6, 1]}
    )

    ax_h.bar(par_heure.index, par_heure["taux_fraude"], color=BLEU, width=0.8)
    ax_h.axhline(taux_global, color=ENCRE, linewidth=1, linestyle="--")
    ax_h.annotate(
        f"moyenne {taux_global:.1%}",
        (12, taux_global),
        xytext=(0, 18),
        textcoords="offset points",
        ha="center",
        fontsize=8,
        color=ENCRE_SECONDAIRE,
        bbox={"boxstyle": "round,pad=0.2", "facecolor": SURFACE, "edgecolor": "none"},
    )
    ax_h.set_xticks(range(0, 24, 2))
    ax_h.set_xlabel("Heure de la transaction")
    ax_h.set_ylabel("Taux de fraude")
    ax_h.yaxis.set_major_formatter(PercentFormatter(1.0, decimals=0))
    ax_h.set_title("Par tranche horaire", loc="left", fontsize=11)
    _style_axes(ax_h)

    ax_z.barh(par_zone.index, par_zone["taux_fraude"], color=BLEU, height=0.7)
    for y, (taux, n) in enumerate(zip(par_zone["taux_fraude"], par_zone["transactions"])):
        ax_z.annotate(
            f"{taux:.2%}",
            (taux, y),
            xytext=(3, 0),
            textcoords="offset points",
            va="center",
            fontsize=8,
            color=ENCRE_SECONDAIRE,
        )
    ax_z.axvline(taux_global, color=ENCRE, linewidth=1, linestyle="--")
    ax_z.set_xlabel("Taux de fraude")
    ax_z.xaxis.set_major_formatter(PercentFormatter(1.0, decimals=2))
    ax_z.set_title("Par zone", loc="left", fontsize=11)
    _style_axes(ax_z, grille="x")

    figure.suptitle("Taux de fraude par heure et par zone", color=ENCRE, x=0.01, ha="left")
    figure.tight_layout()
    return figure


# --------------------------------------------------------------------------
# Q3 — concentration du volume
# --------------------------------------------------------------------------


def calculer_concentration_volume(
    df: pd.DataFrame, part_comptes: float = 0.01
) -> dict[str, float]:
    """Part du volume (GNF émis) portée par les ``part_comptes`` comptes les plus actifs.

    « Plus actif » s'entend en nombre d'opérations émises ; la part en
    volume par les comptes au plus fort volume est donnée aussi.
    """
    if not 0 < part_comptes <= 1:
        raise ValueError("part_comptes doit être dans ]0 ; 1]")
    par_compte = df.groupby("id_emetteur")["montant"].agg(["size", "sum"])
    nb_retenus = max(1, int(round(len(par_compte) * part_comptes)))
    volume_total = par_compte["sum"].sum()
    top_activite = par_compte.nlargest(nb_retenus, "size")
    top_volume = par_compte.nlargest(nb_retenus, "sum")
    return {
        "nb_comptes_emetteurs": int(len(par_compte)),
        "nb_comptes_retenus": nb_retenus,
        "part_volume_plus_actifs": float(top_activite["sum"].sum() / volume_total),
        "part_operations_plus_actifs": float(
            top_activite["size"].sum() / par_compte["size"].sum()
        ),
        "part_volume_plus_gros_volumes": float(top_volume["sum"].sum() / volume_total),
        "types_comptes_plus_actifs": dict(top_activite.index.str[0].value_counts()),
    }


def tracer_courbe_concentration(df: pd.DataFrame) -> Figure:
    """Courbe de Lorenz : part cumulée du volume selon la part
    des comptes (les plus actifs d'abord)."""
    par_compte = (
        df.groupby("id_emetteur")["montant"]
        .agg(["size", "sum"])
        .sort_values("size", ascending=False)
    )
    part_comptes = [rang / len(par_compte) for rang in range(1, len(par_compte) + 1)]
    part_volume = par_compte["sum"].cumsum() / par_compte["sum"].sum()
    centile = calculer_concentration_volume(df)
    figure, ax = _nouvelle_figure(7, 5)
    ax.plot(part_comptes, part_volume, color=BLEU, linewidth=2)
    ax.plot([0, 1], [0, 1], color=ENCRE_DISCRETE, linewidth=1, linestyle=":")
    ax.scatter(
        [0.01], [centile["part_volume_plus_actifs"]], s=40, color=BLEU, edgecolor=SURFACE, zorder=3
    )
    ax.annotate(
        f"1 % des comptes les plus actifs : {centile['part_volume_plus_actifs']:.1%} du volume",
        (0.01, centile["part_volume_plus_actifs"]),
        xytext=(12, -4),
        textcoords="offset points",
        fontsize=9,
        color=ENCRE,
    )
    ax.annotate("répartition égale", (0.62, 0.6), rotation=35, fontsize=8, color=ENCRE_DISCRETE)
    ax.xaxis.set_major_formatter(PercentFormatter(1.0, decimals=0))
    ax.yaxis.set_major_formatter(PercentFormatter(1.0, decimals=0))
    ax.set_xlabel("Part des comptes émetteurs (classés du plus actif au moins actif)")
    ax.set_ylabel("Part cumulée du volume émis (GNF)")
    ax.set_title("Concentration du volume par compte", loc="left")
    _style_axes(ax, grille="both")
    figure.tight_layout()
    return figure


# --------------------------------------------------------------------------
# Q4 — délai entre transactions successives
# --------------------------------------------------------------------------


def ajouter_delai_precedent(df: pd.DataFrame) -> pd.DataFrame:
    """Ajoute ``delai_precedent_min`` : minutes écoulées depuis
    la transaction précédente du même émetteur."""
    trie = df.sort_values(["id_emetteur", "horodatage", "id_transaction"]).copy()
    trie["delai_precedent_min"] = (
        trie.groupby("id_emetteur")["horodatage"].diff().dt.total_seconds() / 60.0
    )
    return trie.sort_index()


def calculer_delai_median(df: pd.DataFrame) -> pd.DataFrame:
    """Délai médian (minutes) depuis la transaction précédente du même émetteur, fraude ou non.

    Les comptes agents sont exclus : leur activité de guichet (des centaines
    de dépôts par jour) écraserait la comparaison.
    """
    _exiger_etiquette(df)
    avec_delai = ajouter_delai_precedent(df).dropna(subset=["delai_precedent_min"])
    avec_delai = avec_delai[~avec_delai["type"].eq("depot")]
    resultat = avec_delai.groupby("est_fraude")["delai_precedent_min"].agg(
        transactions="size",
        delai_median_min="median",
        premier_quartile_min=lambda s: s.quantile(0.25),
        troisieme_quartile_min=lambda s: s.quantile(0.75),
    )
    resultat.index = resultat.index.map({0: "légitime", 1: "frauduleuse"})
    return resultat


def tracer_delai_median(df: pd.DataFrame) -> Figure:
    """Distribution (boîtes, échelle log) du délai depuis la
    transaction précédente, fraude ou non."""
    avec_delai = ajouter_delai_precedent(df).dropna(subset=["delai_precedent_min"])
    avec_delai = avec_delai[~avec_delai["type"].eq("depot")]
    legit = avec_delai.loc[avec_delai["est_fraude"] == 0, "delai_precedent_min"].clip(lower=0.1)
    fraude = avec_delai.loc[avec_delai["est_fraude"] == 1, "delai_precedent_min"].clip(lower=0.1)
    figure, ax = _nouvelle_figure(8, 4)
    boites = ax.boxplot(
        [legit, fraude],
        orientation="horizontal",
        widths=0.5,
        patch_artist=True,
        showfliers=False,
        tick_labels=["Légitimes", "Frauduleuses"],
        medianprops={"color": ENCRE, "linewidth": 1.5},
    )
    for boite, couleur in zip(boites["boxes"], (BLEU, ORANGE)):
        boite.set_facecolor(couleur)
        boite.set_edgecolor(couleur)
    for y, serie in enumerate((legit, fraude), start=1):
        mediane = serie.median()
        ax.annotate(
            f"médiane : {_format_minutes(mediane)}",
            (mediane, y + 0.3),
            ha="center",
            fontsize=9,
            color=ENCRE,
        )
    ax.set_xscale("log")
    ax.set_xlabel("Délai depuis la transaction précédente du même émetteur (minutes, échelle log)")
    ax.set_title("Délai entre deux transactions successives d'un compte", loc="left")
    _style_axes(ax, grille="x")
    figure.tight_layout()
    return figure


def _format_minutes(minutes: float) -> str:
    if minutes < 60:
        return f"{minutes:.0f} min"
    if minutes < 48 * 60:
        return f"{minutes / 60:.1f} h"
    return f"{minutes / 1440:.1f} j"


# --------------------------------------------------------------------------
# Q5 — ancienneté et fraude
# --------------------------------------------------------------------------


def ajouter_anciennete(df: pd.DataFrame) -> pd.DataFrame:
    """Ajoute ``anciennete_jours`` : jours écoulés depuis la première apparition de l'émetteur.

    Le fichier ne contient pas de date d'ouverture : l'ancienneté est
    estimée par la première transaction (émise ou reçue) du compte dans les
    données. Les comptes déjà présents au début de la période paraissent
    donc « jeunes » pendant les premiers jours ; on l'indique dans le rapport.
    """
    premieres = (
        pd.concat(
            [
                df[["id_emetteur", "horodatage"]].rename(columns={"id_emetteur": "compte"}),
                df[["id_destinataire", "horodatage"]].rename(
                    columns={"id_destinataire": "compte"}
                ),
            ]
        )
        .groupby("compte")["horodatage"]
        .min()
    )
    resultat = df.copy()
    resultat["anciennete_jours"] = (
        resultat["horodatage"] - resultat["id_emetteur"].map(premieres)
    ).dt.total_seconds() / 86_400
    return resultat


def calculer_fraude_par_anciennete(df: pd.DataFrame, marge_debut_jours: int = 30) -> pd.DataFrame:
    """Taux de fraude par tranche d'ancienneté de l'émetteur.

    Args:
        marge_debut_jours: les transactions des premiers jours de la période
            sont écartées, car l'ancienneté de tous les comptes y est
            artificiellement faible (biais de censure à gauche).
    """
    _exiger_etiquette(df)
    avec = ajouter_anciennete(df)
    avec = avec[
        avec["horodatage"] >= avec["horodatage"].min() + pd.Timedelta(days=marge_debut_jours)
    ]
    bornes = [b for b, _, _ in TRANCHES_ANCIENNETE] + [TRANCHES_ANCIENNETE[-1][1]]
    libelles = [libelle for _, _, libelle in TRANCHES_ANCIENNETE]
    avec["tranche"] = pd.cut(avec["anciennete_jours"], bins=bornes, labels=libelles, right=False)
    groupes = avec.groupby("tranche", observed=False)["est_fraude"]
    resultat = pd.DataFrame({"transactions": groupes.size(), "fraudes": groupes.sum()})
    resultat["taux_fraude"] = (resultat["fraudes"] / resultat["transactions"]).fillna(0.0)
    return resultat


def tracer_fraude_par_anciennete(df: pd.DataFrame) -> Figure:
    """Barres : taux de fraude par tranche d'ancienneté de l'émetteur."""
    resultat = calculer_fraude_par_anciennete(df)
    figure, ax = _nouvelle_figure(8, 4.5)
    positions = range(len(resultat))
    ax.bar(positions, resultat["taux_fraude"], color=BLEU, width=0.6)
    for x, (taux, n) in enumerate(zip(resultat["taux_fraude"], resultat["transactions"])):
        ax.annotate(
            f"{taux:.1%}\n(n = {n:,})".replace(",", " "),
            (x, taux),
            xytext=(0, 3),
            textcoords="offset points",
            ha="center",
            fontsize=8,
            color=ENCRE_SECONDAIRE,
        )
    ax.set_xticks(list(positions), resultat.index.astype(str))
    ax.yaxis.set_major_formatter(PercentFormatter(1.0, decimals=0))
    ax.set_xlabel("Ancienneté de l'émetteur (depuis sa première apparition)")
    ax.set_ylabel("Taux de fraude")
    ax.set_title("Taux de fraude selon l'ancienneté du compte émetteur", loc="left")
    ax.margins(y=0.2)
    _style_axes(ax)
    figure.tight_layout()
    return figure


# --------------------------------------------------------------------------
# Q6 — question libre : nouvel appareil
# --------------------------------------------------------------------------


def calculer_fraude_nouvel_appareil(df: pd.DataFrame) -> pd.DataFrame:
    """Taux de fraude selon que l'appareil est déjà connu de
    l'émetteur ou utilisé pour la première fois.

    Seules les transactions dont l'émetteur a au moins une opération
    antérieure sont retenues (sinon « nouveau » n'a pas de sens). Le
    calcul est causal : on ne regarde que le passé de chaque transaction.

    Pourquoi cette question ? Un changement d'appareil est le signe le plus
    direct d'une prise de contrôle de compte (vol de téléphone, SIM swap,
    identifiants hameçonnés). Si le taux de fraude y est nettement plus
    élevé, une règle « nouvel appareil » est justifiée — mais il faut aussi
    mesurer combien de transactions légitimes elle toucherait (changement
    de téléphone, second appareil), d'où la colonne ``transactions``.
    """
    _exiger_etiquette(df)
    trie = df.sort_values(["horodatage", "id_transaction"])
    rang_compte = trie.groupby("id_emetteur").cumcount()
    rang_couple = trie.groupby(["id_emetteur", "appareil_id"]).cumcount()
    retenu = trie[rang_compte > 0].assign(
        appareil=lambda d: (rang_couple[rang_compte > 0] == 0).map(
            {True: "nouvel appareil", False: "appareil connu"}
        )
    )
    groupes = retenu.groupby("appareil")["est_fraude"]
    resultat = pd.DataFrame({"transactions": groupes.size(), "fraudes": groupes.sum()})
    resultat["taux_fraude"] = resultat["fraudes"] / resultat["transactions"]
    resultat["part_des_fraudes"] = resultat["fraudes"] / resultat["fraudes"].sum()
    return resultat


def tracer_fraude_nouvel_appareil(df: pd.DataFrame) -> Figure:
    """Barres : taux de fraude, appareil connu contre nouvel appareil."""
    resultat = calculer_fraude_nouvel_appareil(df).reindex(["appareil connu", "nouvel appareil"])
    figure, ax = _nouvelle_figure(6, 4)
    ax.bar([0, 1], resultat["taux_fraude"], color=[BLEU, ORANGE], width=0.55)
    for x, (taux, n) in enumerate(zip(resultat["taux_fraude"], resultat["transactions"])):
        ax.annotate(
            f"{taux:.1%}\n(n = {int(n):,})".replace(",", " "),
            (x, taux),
            xytext=(0, 3),
            textcoords="offset points",
            ha="center",
            fontsize=9,
            color=ENCRE_SECONDAIRE,
        )
    ax.set_xticks([0, 1], ["Appareil déjà utilisé", "Appareil jamais vu"])
    ax.yaxis.set_major_formatter(PercentFormatter(1.0, decimals=0))
    ax.set_ylabel("Taux de fraude")
    ax.set_title("Fraude et appareil utilisé", loc="left")
    ax.margins(y=0.2)
    _style_axes(ax)
    figure.tight_layout()
    return figure


# --------------------------------------------------------------------------
# Analyse complète
# --------------------------------------------------------------------------


def analyser(df: pd.DataFrame, dossier_figures: str | Path | None = None) -> dict[str, Any]:
    """Exécute toutes les analyses ; enregistre les figures si ``dossier_figures`` est fourni.

    Returns:
        Dictionnaire des résultats chiffrés (et des chemins des figures).
    """
    _exiger_etiquette(df)
    resultats: dict[str, Any] = {
        "nb_transactions": int(len(df)),
        "taux_fraude_global": float(df["est_fraude"].mean()),
        "montants_par_type": calculer_montants_par_type(df),
        "fraude_par_heure": calculer_taux_fraude_par_heure(df),
        "fraude_par_zone": calculer_taux_fraude_par_zone(df),
        "concentration": calculer_concentration_volume(df),
        "delai_median": calculer_delai_median(df),
        "fraude_par_anciennete": calculer_fraude_par_anciennete(df),
        "fraude_nouvel_appareil": calculer_fraude_nouvel_appareil(df),
    }
    if dossier_figures is not None:
        dossier = Path(dossier_figures)
        figures = {
            "montants_par_type.png": tracer_montants_par_type,
            "fraude_heure_zone.png": tracer_taux_fraude_heure_zone,
            "concentration_volume.png": tracer_courbe_concentration,
            "delai_transactions.png": tracer_delai_median,
            "fraude_anciennete.png": tracer_fraude_par_anciennete,
            "fraude_nouvel_appareil.png": tracer_fraude_nouvel_appareil,
        }
        resultats["figures"] = [
            str(enregistrer_figure(tracer(df), dossier / nom)) for nom, tracer in figures.items()
        ]
        journal.info("%d figures enregistrées dans %s", len(figures), dossier)
    return resultats
