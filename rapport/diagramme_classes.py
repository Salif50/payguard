"""Dessine le diagramme de classes de PayGuard (rapport/figures/diagramme_classes.png).

Script de documentation (hors paquet) : il ne contient aucune logique métier, seulement
la mise en page du diagramme UML simplifié. Exécution : ``python rapport/diagramme_classes.py``.
"""

from __future__ import annotations

from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
from matplotlib.patches import FancyBboxPatch, Polygon  # noqa: E402

ENCRE = "#0b0b0b"
ENCRE_2 = "#52514e"
TRAIT = "#52514e"
FONDS = {"comptes": "#e8f1fc", "outils": "#f4f3ee", "donnees": "#eaf6f0", "detection": "#fdeee7"}
BORDS = {"comptes": "#2a78d6", "outils": "#898781", "donnees": "#1baf7a", "detection": "#eb6834"}

# nom -> (x, y, largeur, hauteur, paquet, stéréotype, membres)
CLASSES: dict[str, tuple] = {
    "Client": (2, 58, 19, 8, "comptes", "", ["nom: str «property validée»", "telephone: str «+224 6…»"]),
    "Compte": (26, 47, 25, 21, "comptes", "«abstract»", [
        "- _solde: int (lecture seule)", "- _gele: bool", "+ type_compte()*", "+ plafond_operation(type)*",
        "+ plafond_journalier()*", "+ calculer_frais(type, m)*", "+ debiter() / crediter()",
        "+ capturer_etat() / restaurer_etat()", "__eq__ __hash__ __lt__ __repr__"]),
    "ComptePersonnel": (29, 34, 16, 6, "comptes", "", ["5 M/op, 15 M/jour"]),
    "CompteMarchand": (47, 34, 16, 6, "comptes", "", ["20 M retrait"]),
    "CompteAgent": (65, 34, 14, 6, "comptes", "", ["dépôts, 500 M/jour"]),
    "RegistreComptes": (2, 17, 21, 12, "comptes", "", [
        "+ filtrer(predicat)", "+ par_type(classe)", "+ tries(cle)",
        "__len__ __iter__", "__contains__ __getitem__"]),
    "Plateforme": (27, 14, 25, 15, "comptes", "", [
        "+ executer(type, ém., dest., m)", "+ deposer / retirer", "+ transferer / payer",
        "+ operations_groupees()", "__len__ __iter__ __contains__"]),
    "Transaction": (2, 1, 21, 12, "comptes", "«dataclass frozen»", [
        "id, horodatage, émetteur,", "destinataire, montant, zone,", "appareil_id, est_fraude", "__lt__ chronologique"]),
    "TypeTransaction": (27, 1, 20, 9, "comptes", "«StrEnum»", ["depot, retrait, transfert,", "paiement_marchand"]),
    "TransactionAtomique": (56, 17, 19, 9, "outils", "«context manager»", ["__enter__ : capture", "__exit__ : restaure"]),
    "Depot": (56, 2, 19, 10, "donnees", "«repository SQLite»", ["seul module avec du SQL", "persiste les Transaction", "requêtes paramétrées"]),
    "ProfilsComptes": (80, 1, 19, 10, "donnees", "", ["+ calculer_python()", "+ calculer_pandas()", "1..* ProfilCompte"]),
    "Regle": (97, 55, 25, 13, "detection", "«abstract»", [
        "+ nom, identifiant, poids", "+ evaluer(transaction, profil)*", "  -> ResultatRegle", "+ creer(nom, …)  (fabrique)"]),
    "MoteurDeRegles": (80, 16, 22, 12, "detection", "«patron Stratégie»", [
        "+ ajouter_regle / retirer_regle", "+ analyser(flux) -> Evaluation", "+ detecter(flux) -> Alerte", "profils causaux"]),
    "Alerte": (105, 21, 19, 9, "detection", "«dataclass frozen»", ["transaction, score,", "règles, motifs"]),
    "Evaluation": (105, 10.5, 19, 9, "detection", "«dataclass frozen»", ["transaction, score,", "déclenchements"]),
    "ConfigurationMoteur": (105, 0, 21, 9.5, "detection", "", ["+ depuis_dict() (validation)", "+ construire_moteur()", "charger_configuration(json)"]),
}
REGLES = ["RegleMontantAnormal", "RegleMontantEleve", "RegleRafale", "RegleHoraireInhabituel",
          "RegleChangementZone", "RegleNouvelAppareil", "RegleCompteRecentVide"]


def boite(ax, nom: str) -> None:
    x, y, l, h, paquet, stereo, membres = CLASSES[nom]
    ax.add_patch(FancyBboxPatch((x, y), l, h, boxstyle="round,pad=0.15,rounding_size=0.6",
                                facecolor=FONDS[paquet], edgecolor=BORDS[paquet], linewidth=1.3))
    haut = y + h - 1.6
    if stereo:
        ax.text(x + l / 2, haut, stereo, ha="center", va="center", fontsize=6.5, color=ENCRE_2, style="italic")
        haut -= 1.8
    italique = "italic" if stereo == "«abstract»" else "normal"
    ax.text(x + l / 2, haut, nom, ha="center", va="center", fontsize=9, weight="bold", color=ENCRE, style=italique)
    ax.plot([x + 0.4, x + l - 0.4], [haut - 1.2, haut - 1.2], color=BORDS[paquet], linewidth=0.7)
    for i, membre in enumerate(membres):
        ax.text(x + 0.8, haut - 2.6 - 1.75 * i, membre, ha="left", va="center", fontsize=6.6, color=ENCRE,
                family="monospace")


def ancre(nom: str, cote: str, decalage: float = 0.5) -> tuple[float, float]:
    x, y, l, h, *_ = CLASSES[nom]
    return {"haut": (x + l * decalage, y + h), "bas": (x + l * decalage, y),
            "gauche": (x, y + h * decalage), "droite": (x + l, y + h * decalage)}[cote]


def heritage(ax, enfant: tuple[float, float], parent: tuple[float, float]) -> None:
    """Trait plein terminé par un triangle creux côté parent."""
    ax.plot([enfant[0], parent[0]], [enfant[1], parent[1] - 1.4], color=TRAIT, linewidth=1)
    px, py = parent
    ax.add_patch(Polygon([(px, py), (px - 0.9, py - 1.4), (px + 0.9, py - 1.4)], closed=True,
                         facecolor="white", edgecolor=TRAIT, linewidth=1, zorder=3))


def losange(ax, proprietaire: tuple[float, float], partie: tuple[float, float], plein: bool, etiquette: str = "") -> None:
    """Composition (losange plein) ou agrégation (losange creux) côté propriétaire."""
    (x0, y0), (x1, y1) = proprietaire, partie
    dx, dy = x1 - x0, y1 - y0
    norme = (dx * dx + dy * dy) ** 0.5
    ux, uy = dx / norme, dy / norme
    pointe = (x0 + 2.4 * ux, y0 + 2.4 * uy)
    milieu = (x0 + 1.2 * ux, y0 + 1.2 * uy)
    cote = (-uy * 0.7, ux * 0.7)
    ax.add_patch(Polygon([(x0, y0), (milieu[0] + cote[0], milieu[1] + cote[1]), pointe,
                          (milieu[0] - cote[0], milieu[1] - cote[1])], closed=True,
                         facecolor=TRAIT if plein else "white", edgecolor=TRAIT, linewidth=1, zorder=3))
    ax.plot([pointe[0], x1], [pointe[1], y1], color=TRAIT, linewidth=1)
    if etiquette:
        ax.text((x0 + x1) / 2, (y0 + y1) / 2 + 0.8, etiquette, fontsize=6.5, color=ENCRE_2, ha="center")


def dependance(ax, depart: tuple[float, float], arrivee: tuple[float, float], etiquette: str = "") -> None:
    """Flèche pointillée : « utilise »."""
    ax.annotate("", xy=arrivee, xytext=depart,
                arrowprops={"arrowstyle": "->", "color": TRAIT, "linestyle": "--", "linewidth": 0.9})
    if etiquette:
        ax.text((depart[0] + arrivee[0]) / 2, (depart[1] + arrivee[1]) / 2 + 0.8, etiquette, fontsize=6.5,
                color=ENCRE_2, ha="center", style="italic")


def dessiner(chemin: Path) -> Path:
    figure, ax = plt.subplots(figsize=(19, 9.5), facecolor="white")
    ax.set_xlim(0, 146)
    ax.set_ylim(-1, 71)
    ax.axis("off")

    for nom in CLASSES:
        boite(ax, nom)
    # Les sept règles concrètes : deux rangées de petites boîtes sous Regle.
    positions = [(82, 43), (98, 43), (114, 43), (130, 43), (90, 36.5), (106, 36.5), (122, 36.5)]
    for nom, (x, y) in zip(REGLES, positions):
        ax.add_patch(FancyBboxPatch((x, y), 15, 4.5, boxstyle="round,pad=0.15,rounding_size=0.5",
                                    facecolor=FONDS["detection"], edgecolor=BORDS["detection"], linewidth=1))
        ax.text(x + 7.5, y + 2.25, nom, ha="center", va="center", fontsize=6.6, weight="bold", color=ENCRE)
    bus = 51.5
    ax.plot([89.5, 137.5], [bus, bus], color=TRAIT, linewidth=1)
    for x, y in positions:
        ax.plot([x + 7.5, x + 7.5], [y + 4.65, bus], color=TRAIT, linewidth=1)
    heritage(ax, (109.5, bus), ancre("Regle", "bas"))

    # Comptes : héritage, composition, agrégation.
    for enfant in ("ComptePersonnel", "CompteMarchand", "CompteAgent"):
        heritage(ax, ancre(enfant, "haut"), ancre("Compte", "bas"))
    losange(ax, ancre("Compte", "gauche", 0.62), ancre("Client", "droite"), plein=False, etiquette="titulaire")
    losange(ax, ancre("Plateforme", "gauche", 0.6), ancre("RegistreComptes", "droite", 0.6), plein=True)
    losange(ax, ancre("RegistreComptes", "haut", 0.5), ancre("Compte", "gauche", 0.15), plein=False, etiquette="0..*")
    losange(ax, ancre("Plateforme", "bas", 0.25), ancre("Transaction", "droite", 0.7), plein=True,
            etiquette="historique 0..*")
    dependance(ax, ancre("Transaction", "droite", 0.25), ancre("TypeTransaction", "gauche", 0.5))
    dependance(ax, ancre("Plateforme", "droite", 0.75), ancre("TransactionAtomique", "gauche", 0.6), "utilise")

    # Détection.
    losange(ax, ancre("MoteurDeRegles", "haut", 0.5), (91, 36.5), plein=False, etiquette="stratégies 1..*")
    dependance(ax, ancre("MoteurDeRegles", "droite", 0.75), ancre("Alerte", "gauche", 0.5), "produit")
    dependance(ax, ancre("MoteurDeRegles", "droite", 0.3), ancre("Evaluation", "gauche", 0.5))
    dependance(ax, ancre("MoteurDeRegles", "bas", 0.5), ancre("ProfilsComptes", "haut", 0.5), "profils")
    dependance(ax, ancre("ConfigurationMoteur", "gauche", 0.6), ancre("MoteurDeRegles", "bas", 0.88))
    ax.text(101.5, 9.5, "fabrique", fontsize=6.5, color=ENCRE_2, style="italic", ha="center")

    # Légende.
    for i, (paquet, libelle) in enumerate([("comptes", "payguard.comptes"), ("outils", "payguard.outils"),
                                            ("donnees", "payguard.donnees"), ("detection", "payguard.detection")]):
        ax.add_patch(FancyBboxPatch((2 + 22 * i, 68.2), 3, 1.8, boxstyle="round,pad=0.1",
                                    facecolor=FONDS[paquet], edgecolor=BORDS[paquet]))
        ax.text(6 + 22 * i, 69.1, libelle, fontsize=8, va="center", color=ENCRE)
    ax.text(92, 69.1, "triangle creux : héritage   losange plein : composition   losange creux : agrégation"
            "   pointillés : dépendance   * : méthode abstraite", fontsize=7, va="center", color=ENCRE_2)

    chemin.parent.mkdir(parents=True, exist_ok=True)
    figure.savefig(chemin, dpi=170, bbox_inches="tight", facecolor="white")
    plt.close(figure)
    return chemin


if __name__ == "__main__":
    print(dessiner(Path(__file__).resolve().parent / "figures" / "diagramme_classes.png"))
