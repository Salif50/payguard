# PayGuard

**Simulation d'un système de paiement mobile (en francs guinéens) et détection de fraude par règles métier.**

Projet du module *Programmation Python et introduction à la science des données* (Master 1 IASD), réalisé en binôme.
PayGuard est une bibliothèque Python installable. Elle génère des transactions synthétiques, modélise les comptes
et la plateforme en objets, stocke et analyse l'historique (SQLite, pandas, Matplotlib), puis signale les opérations
suspectes avec un moteur de règles configurable. Le projet n'utilise **aucun apprentissage automatique**.

---

## Sommaire

1. [Installation (moins de 10 minutes)](#1-installation)
2. [Démarrage rapide](#2-démarrage-rapide)
3. [Commandes](#3-commandes)
4. [Architecture](#4-architecture)
5. [Données et scénarios de fraude](#5-données-et-scénarios-de-fraude)
6. [Moteur de règles](#6-moteur-de-règles)
7. [Résultats obtenus](#7-résultats-obtenus)
8. [Tests et qualité](#8-tests-et-qualité)
9. [Reproductibilité](#9-reproductibilité)
10. [Démonstration (notebook)](#10-démonstration)
11. [Limites](#11-limites)
12. [Contribuer et licence](#12-contribuer-et-licence)

---

## 1. Installation

**Prérequis :** Python 3.11 ou plus récent, `pip` et `git`.

```bash
git clone <url-du-depot> payguard        # ou décompresser l'archive
cd payguard
python3 -m venv .venv
source .venv/bin/activate                # Windows : .venv\Scripts\activate
pip install -e ".[dev]"                  # paquet + pytest + pytest-cov
payguard --version                       # vérification : « payguard 1.0.0 »
```

Dépendances installées : `pandas`, `matplotlib` (et `pytest`, `pytest-cov` avec `[dev]`).
Pour ouvrir le notebook, ajoutez `pip install -e ".[notebook]"`.
Les phases 1 à 3 n'utilisent que la bibliothèque standard.

## 2. Démarrage rapide

```bash
payguard simuler                                   # ~2 s : 122 927 transactions + base SQLite
payguard analyser --benchmark                      # analyse, 6 figures dans rapport/figures/
payguard detecter data/processed/transactions.csv --limite 10 --details
payguard evaluer -c config/regles.json config/reglages/equilibre.json config/reglages/prudent.json
pytest                                             # 163 tests
```

**Jeu de test inédit (soutenance).** Sur un fichier au format de l'annexe A, avec ou sans la colonne `est_fraude` :

```bash
payguard detecter chemin/vers/jeu_inedit.csv -o alertes.csv
```

La commande accepte un fichier non trié, un BOM UTF-8, des lignes vides, des types en majuscules, des montants
`1500.0`. Les lignes invalides sont ignorées, comptées et signalées, sans faire échouer la commande.
Sans l'option `-c`, elle utilise `config/regles.json` s'il existe, sinon la configuration intégrée au paquet,
qui est identique.

## 3. Commandes

`payguard <commande> --help` décrit chaque option. Options globales : `--journal FICHIER` (défaut :
`data/payguard.log`) et `-v` (journal détaillé).

| Commande | Rôle | Exemple |
|---|---|---|
| `generer` | Phase 1 : CSV brut produit par le générateur (bibliothèque standard) | `payguard generer --comptes 5000 --operations 110000 --graine 42` |
| `simuler` | Phase 2 : exécute les opérations sur la plateforme (soldes, plafonds, frais), écrit le CSV accepté et la base SQLite | `payguard simuler --graine 2026 -o data/validation/t.csv --sans-base` |
| `analyser` | Phase 4 : les 6 analyses, les figures, la comparaison des profils Python pur / pandas | `payguard analyser --base data/payguard.db --benchmark` |
| `detecter` | Phase 5 : alertes et règles déclenchées pour chaque transaction signalée, CSV des alertes | `payguard detecter fichier.csv --details --limite 20` |
| `evaluer` | Phase 5 : détections, manques, fausses alertes, coût métier, comparaison de réglages | `payguard evaluer --seuils 1 3 --scenarios data/processed/scenarios.csv --mensuel` |

Codes de sortie : `0` succès, `1` erreur métier (message explicite sur la sortie d'erreur), `2` arguments
invalides, `130` interruption.

Options utiles de `detecter` : `--details` (motifs lisibles), `--limite N` (affichage seulement : le CSV contient
toutes les alertes), `--flux` (lecture au fil de l'eau sans charger le fichier, qui doit alors être trié),
`--historique CSV` (profils initialisés sur un historique), `--strict`, `--base DB` (alertes enregistrées en SQLite).

## 4. Architecture

```text
payguard/
├── pyproject.toml            paquet installable (pip install -e .), commande « payguard »
├── config/regles.json        configuration retenue du moteur ; config/reglages/ : réglages comparés
├── data/                     (généré, non versionné)
├── notebooks/demo.ipynb      démonstration, sans logique métier
├── rapport/                  éléments du rapport, figures/, resultats/
├── src/payguard/
│   ├── exceptions.py         PayGuardError et ses sous-classes
│   ├── schema.py             format de l'annexe A (partagé par toutes les couches)
│   ├── journal.py            configuration de logging
│   ├── cli.py                argparse : generer, simuler, analyser, detecter, evaluer
│   ├── generation/           generateur.py, scenarios.py, parametres.py, simulation.py
│   ├── comptes/              base.py, personnel.py, marchand.py, agent.py, client.py,
│   │                         transaction.py, plateforme.py, registre.py
│   ├── outils/               decorateurs.py, contextes.py, flux.py
│   ├── donnees/              depot.py, profils.py, analyse.py
│   └── detection/            base.py, regles.py, moteur.py, alerte.py, configuration.py, evaluation.py
└── tests/                    163 tests pytest
```

Les dépendances vont dans un seul sens et ne forment aucun cycle :
`generation (phase 1) → schema` ; `comptes → outils.contextes` ; `donnees → comptes` ; `detection → donnees, comptes` ;
`cli → tout`. Le module `outils.contextes` ne connaît pas les comptes : il travaille sur un `Protocol`
(`capturer_etat` / `restaurer_etat`). Modules ajoutés à l'arborescence imposée : `schema.py`, `journal.py`,
`generation/parametres.py`, `generation/simulation.py`, `comptes/registre.py`.

Principaux choix de conception, détaillés dans le rapport :

- **`Compte` abstrait, méthode patron.** `debiter` applique toujours les contrôles dans le même ordre : gel, type
  autorisé, plafond par opération, plafond journalier, solde frais compris. Les classes filles fournissent les
  plafonds, les frais et les types autorisés (polymorphisme).
- **Atomicité par mémento.** `TransactionAtomique` capture l'état des comptes et le restaure si une jambe de
  l'opération échoue. La plateforme n'enregistre la transaction qu'après les deux jambes.
- **Transaction immuable.** Dataclass figée avec un ordre chronologique naturel.
- **Patron Stratégie.** Le moteur ne connaît que l'interface `Regle`. Les règles s'enregistrent automatiquement
  par leur nom (`__init_subclass__`) : une nouvelle classe devient configurable en JSON sans modifier le moteur.
- **Profils causaux.** Chaque transaction est jugée avec le passé de son émetteur, puis intégrée à son profil.
  Le moteur ne lit jamais l'étiquette et fonctionne aussi en flux.

## 5. Données et scénarios de fraude

Générateur par défaut (graine 42) : 5 000 comptes (3 % d'agents, 10 % de marchands, 87 % de particuliers), du
1ᵉʳ janvier au 30 juin 2026, 8 régions de Guinée (Conakry, Kindia, Boké, Labé, Mamou, Kankan, Faranah, Nzérékoré).
Montants log-normaux en GNF, différents selon le type et selon le compte (médianes observées : dépôt ≈ 347 k,
retrait ≈ 256 k, transfert ≈ 140 k, paiement ≈ 46,5 k).

| Scénario | Signal injecté (partiel, pour ne pas être trivial) |
|---|---|
| `montant_eleve` | 6 à 20 fois le montant habituel ; nouvel appareil dans 40 % des cas |
| `rafale` | 3 à 6 transferts en quelques minutes vers des comptes mules |
| `horaire_inhabituel` | 1 ou 2 opérations entre 0 h et 5 h |
| `changement_zone` | retrait dans une région lointaine 15 min à 2 h 30 après une opération légitime |
| `compte_neuf_vide` | compte ouvert depuis moins de 5 jours qui reçoit des fonds puis se vide dans l'heure |
| `nouvel_appareil` | appareil jamais vu, 2 à 10 fois le montant habituel |

Bruit légitime : couche-tard (4 %), changements de téléphone (6 %), seconds appareils, voyages, gros achats et
opérations tentées sans provision. Ces dernières sont rejetées par la plateforme en phase 2 (215 rejets
`SoldeInsuffisant` avec la graine 42).

## 6. Moteur de règles

| Règle | Déclenchement (paramètres de `config/regles.json`) | Poids |
|---|---|---|
| `montant_anormal` | montant ≥ 4 × la moyenne et au-dessus du maximum du compte (≥ 3 opérations passées) | 1 |
| `rafale` | ≥ 2 opérations émises en 5 minutes | 2 |
| `horaire_inhabituel` | entre 0 h et 5 h, plage représentant ≤ 10 % de l'historique | 1 |
| `changement_zone` | autre zone moins de 3 h après la dernière opération, ou zone jamais utilisée | 1 |
| `nouvel_appareil` | appareil inconnu d'un compte ayant ≥ 2 opérations | 2 |
| `compte_recent_vide` | compte apparu depuis ≤ 7 jours qui émet ≥ 80 % des fonds reçus non dépensés | 1 |
| `montant_significatif` | sortie d'argent ≥ 50 000 GNF (dépôts exclus) | 1 |
| `montant_eleve` | sortie d'argent ≥ 150 000 GNF (dépôts exclus) | 1 |

Une alerte est levée quand le **score**, somme des poids des règles déclenchées, atteint **2**. La même stratégie
`montant_eleve` est donc instanciée deux fois, sous deux identifiants : au-delà de 150 000 GNF une sortie est
signalée seule ; entre 50 000 et 150 000 GNF il faut un indice de plus. La configuration JSON est validée
strictement : clé inconnue, règle ou paramètre inconnu, valeur hors bornes, doublon ou absence de règle active
lèvent `ConfigurationInvalide` avec un message précis.

## 7. Résultats obtenus

Mesures réelles, reproductibles avec les commandes de la section 9 (fichiers bruts dans `rapport/resultats/`).
Le coût métier compte le montant de chaque fraude manquée et 500 GNF par alerte injustifiée.

| Réglage (graine 42, 122 927 transactions, 1 829 fraudes) | Alertes | Taux de détection | Précision | Exactitude | Coût métier |
|---|---:|---:|---:|---:|---:|
| Référence : aucune alerte | 0 | 0 % | — | 98,51 % | 949 141 500 GNF |
| Référence : tout signaler | 122 927 | 100 % | 1,49 % | 1,49 % | 60 549 000 GNF |
| **Retenu** (`config/regles.json`) | 40 879 | **95,30 %** | 4,26 % | 68,09 % | **27 281 500 GNF** |
| Équilibré (paliers 200 k / 1 M) | 9 595 | 69,22 % | 13,19 % | 92,77 % | 215 359 500 GNF |
| Prudent (sans palier de montant) | 1 945 | 47,68 % | 44,83 % | 98,35 % | 583 988 500 GNF |

**Validation sur des données jamais utilisées pour le réglage** (graine 2026) : le réglage retenu détecte
95,89 % des fraudes pour un coût de 25 594 500 GNF. Il ne s'est donc pas sur-ajusté.

À lire avec prudence :

- **L'exactitude est trompeuse.** « Ne rien signaler » atteint 98,5 % d'exactitude tout en laissant passer toutes
  les fraudes. C'est pourquoi l'évaluation repose sur les détections, les manques, les fausses alertes et le coût.
- **Ce que révèle le coût.** Une fraude manquée coûte en moyenne environ 520 000 GNF, soit le prix d'environ
  1 000 fausses alertes. Le réglage de coût minimal signale donc beaucoup : environ un tiers des transactions.
  Il n'a de sens que si une alerte est traitée automatiquement (par exemple une confirmation par code). Avec une
  équipe d'analystes humains, le réglage *prudent* serait choisi, au prix d'un coût plus élevé.

Profils de comptes : les implémentations Python pur et pandas donnent des résultats **identiques**. Sur 122 927
transactions (meilleur de 5 essais, Python 3.12, Apple Silicon), Python pur prend 0,114 s, l'agrégation pandas
0,061 s et le calcul pandas complet, conversion en objets comprise, 0,095 s.

## 8. Tests et qualité

```bash
pytest                                                         # 163 tests, ~20 s
pytest --cov=payguard --cov-report=term-missing                # couverture
```

Couverture mesurée : **96 %** au total (paquet `comptes` 97,0 %, paquet `detection` 97,7 % ; minimum exigé : 70 %).
Les tests couvrent les cas nominaux et les cas d'erreur : reproductibilité octet pour octet, format de l'annexe A,
plafonds, gel, atomicité (débit réussi puis crédit refusé), lecture tolérante et stricte, fenêtre glissante aux
bords, injection SQL neutralisée, égalité des profils Python et pandas, causalité du moteur, indépendance vis-à-vis
des étiquettes, 17 configurations JSON invalides et les cinq commandes de la CLI exécutées réellement.

Conventions : PEP 8 (lignes de 99 caractères au plus, vérifié avec `pycodestyle`), annotations de types sur les interfaces publiques, docstrings, `logging` à la place de
`print` (la CLI n'utilise `print` que pour afficher ses résultats).

## 9. Reproductibilité

Tout l'aléa provient d'une instance `random.Random(graine)` : le module `random` global n'est jamais utilisé.

```bash
payguard generer --graine 42     # data/raw/transactions.csv        123 142 lignes
payguard simuler --graine 42     # data/processed/transactions.csv  122 927 lignes (+ data/payguard.db)
shasum -a 256 data/raw/transactions.csv data/processed/transactions.csv
```

Empreintes obtenues (Python 3.12) :

```text
a0f65621e3ec9555ddb38f754dc66a37c930ebc352a02e39a71c3511df194a37  data/raw/transactions.csv
d92db4b7ca593adf9aadb8c48a2ed2e55026615f3440c60e5fb86f928090f429  data/processed/transactions.csv
```

Le jeu de validation se reproduit avec `payguard simuler --graine 2026 -o data/validation/transactions.csv --scenarios data/validation/scenarios.csv --sans-base`.

## 10. Démonstration

```bash
pip install -e ".[notebook]"
jupyter notebook notebooks/demo.ipynb
```

Le notebook parcourt les six phases : génération, objets et atomicité, outils avancés, SQLite et analyses,
détection, évaluation et coût, puis la CLI sur un fichier inconnu. Il n'appelle que des fonctions du paquet
(environ 15 s d'exécution).

## 11. Limites

- **Données synthétiques.** Les règles sont écrites par l'équipe qui connaît les scénarios. Les performances sur
  des fraudes réelles ou sur le jeu de l'enseignant seront plus faibles.
- **Seuils absolus en GNF.** Les paliers de montant (50 000 / 150 000 GNF) supposent des montants comparables à
  ceux de la simulation. Un jeu aux montants très différents demanderait de nouveaux seuils.
- **Ancienneté estimée.** Le format d'échange ne contient pas de date d'ouverture. L'ancienneté est mesurée
  depuis la première apparition du compte dans le fichier, donc tous les comptes paraissent récents au début
  d'un fichier.
- **Démarrage à froid.** Sur un fichier court, beaucoup de comptes n'ont presque pas d'historique, et les règles
  fondées sur le profil (montant anormal, nouvel appareil, zone) se déclenchent moins.
- **Charge d'alertes.** Le réglage de coût minimal signale environ un tiers des transactions (voir section 7).
- **Convention émetteur / destinataire.** Pour un dépôt, l'émetteur est l'agent (compte débité). Un fichier qui
  suivrait une autre convention resterait lisible, mais les profils des agents et des clients y seraient mélangés.

## 12. Contribuer et licence

Les contributions sont bienvenues : lisez [CONTRIBUTING.md](CONTRIBUTING.md) (règles du projet, style,
ajout d'une règle de détection). Le projet est distribué sous licence MIT ([LICENSE](LICENSE)).
