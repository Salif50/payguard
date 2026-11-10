"""Couche de persistance SQLite.

La classe :class:`Depot` (patron *Repository*) est le **seul** endroit du
projet qui contient du SQL. Le reste du code manipule des objets
:class:`~payguard.comptes.transaction.Transaction`, des comptes ou des
alertes, et ignore tout du schéma.

Choix :

* requêtes **paramétrées** (``?``) exclusivement : aucune valeur n'est
  concaténée dans une requête, ce qui exclut l'injection SQL ;
* insertions **par lots** avec ``executemany`` dans une transaction, à
  partir d'un itérable quelconque (un générateur convient : la mémoire
  reste bornée par la taille d'un lot) ;
* horodatages stockés en texte ISO 8601 : l'ordre lexicographique coïncide
  avec l'ordre chronologique, donc ``ORDER BY`` et les bornes ``BETWEEN``
  fonctionnent directement.
"""

from __future__ import annotations

import json
import logging
import sqlite3
from collections.abc import Iterable, Iterator
from datetime import datetime
from itertools import islice
from pathlib import Path
from types import TracebackType
from typing import TYPE_CHECKING, Any

from payguard.comptes.base import Compte
from payguard.comptes.transaction import Transaction, TypeTransaction
from payguard.exceptions import DepotError, ParametreInvalide
from payguard.outils.decorateurs import chronometre, reessayer

if TYPE_CHECKING:
    import pandas as pd

    from payguard.detection.alerte import Alerte

journal = logging.getLogger(__name__)

_SCHEMA = """
CREATE TABLE IF NOT EXISTS comptes (
    id_compte      TEXT PRIMARY KEY,
    type_compte    TEXT NOT NULL,
    id_client      TEXT NOT NULL,
    nom            TEXT NOT NULL,
    telephone      TEXT NOT NULL,
    solde          INTEGER NOT NULL CHECK (solde >= 0),
    gele           INTEGER NOT NULL DEFAULT 0 CHECK (gele IN (0, 1)),
    date_ouverture TEXT
);
CREATE TABLE IF NOT EXISTS transactions (
    id_transaction  TEXT PRIMARY KEY,
    horodatage      TEXT NOT NULL,
    id_emetteur     TEXT NOT NULL,
    id_destinataire TEXT NOT NULL,
    type            TEXT NOT NULL
                    CHECK (type IN ('depot', 'retrait', 'transfert', 'paiement_marchand')),
    montant         INTEGER NOT NULL CHECK (montant > 0),
    zone            TEXT NOT NULL,
    appareil_id     TEXT NOT NULL,
    est_fraude      INTEGER CHECK (est_fraude IN (0, 1))
);
CREATE INDEX IF NOT EXISTS idx_transactions_emetteur ON transactions (id_emetteur, horodatage);
CREATE INDEX IF NOT EXISTS idx_transactions_horodatage ON transactions (horodatage);
CREATE TABLE IF NOT EXISTS alertes (
    id_transaction TEXT PRIMARY KEY,
    score          REAL NOT NULL,
    regles         TEXT NOT NULL,
    motifs         TEXT NOT NULL,
    detectee_le    TEXT NOT NULL
);
"""

_INSERTION_TRANSACTION = (
    "INSERT OR REPLACE INTO transactions (id_transaction, horodatage, id_emetteur, "
    "id_destinataire, type, montant, zone, appareil_id, est_fraude) "
    "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)"
)
_COLONNES_SELECTION = (
    "id_transaction, horodatage, id_emetteur, id_destinataire, type, montant, zone, "
    "appareil_id, est_fraude"
)


def _ligne_transaction(t: Transaction) -> tuple[Any, ...]:
    return (
        t.id_transaction,
        t.horodatage.isoformat(timespec="seconds"),
        t.id_emetteur,
        t.id_destinataire,
        t.type.value,
        t.montant,
        t.zone,
        t.appareil_id,
        None if t.est_fraude is None else int(t.est_fraude),
    )


def _vers_transaction(ligne: sqlite3.Row | tuple[Any, ...]) -> Transaction:
    return Transaction(
        id_transaction=ligne[0],
        horodatage=datetime.fromisoformat(ligne[1]),
        id_emetteur=ligne[2],
        id_destinataire=ligne[3],
        type=TypeTransaction(ligne[4]),
        montant=int(ligne[5]),
        zone=ligne[6],
        appareil_id=ligne[7],
        est_fraude=None if ligne[8] is None else bool(ligne[8]),
    )


class Depot:
    """Accès à la base SQLite de PayGuard.

    Utilisable comme gestionnaire de contexte ::

        with Depot("data/payguard.db") as depot:
            depot.inserer_transactions(transactions)
            n = depot.compter_transactions()

    La connexion est ouverte paresseusement au premier besoin, avec de
    nouvelles tentatives si la base est momentanément verrouillée.
    """

    def __init__(self, chemin: str | Path = ":memory:") -> None:
        self._chemin = str(chemin)
        self._connexion: sqlite3.Connection | None = None

    # -- connexion -------------------------------------------------------

    @reessayer(n=3, delai=0.2, exceptions=(sqlite3.OperationalError,), facteur=2.0)
    def _ouvrir(self) -> sqlite3.Connection:
        if self._chemin != ":memory:":
            Path(self._chemin).parent.mkdir(parents=True, exist_ok=True)
        connexion = sqlite3.connect(self._chemin, timeout=5.0)
        connexion.execute("PRAGMA foreign_keys = ON")
        connexion.executescript(_SCHEMA)
        return connexion

    @property
    def connexion(self) -> sqlite3.Connection:
        """Connexion SQLite (ouverte au premier accès, schéma créé si besoin)."""
        if self._connexion is None:
            try:
                self._connexion = self._ouvrir()
            except sqlite3.Error as erreur:
                raise DepotError(
                    f"Impossible d'ouvrir la base {self._chemin} : {erreur}"
                ) from erreur
        return self._connexion

    def fermer(self) -> None:
        """Ferme la connexion (sans effet si elle n'est pas ouverte)."""
        if self._connexion is not None:
            self._connexion.close()
            self._connexion = None

    def __enter__(self) -> Depot:
        _ = self.connexion
        return self

    def __exit__(
        self,
        type_exception: type[BaseException] | None,
        exception: BaseException | None,
        trace: TracebackType | None,
    ) -> None:
        if self._connexion is not None:
            if type_exception is None:
                self._connexion.commit()
            else:
                self._connexion.rollback()
        self.fermer()

    def __repr__(self) -> str:
        return f"Depot({self._chemin!r})"

    # -- écriture --------------------------------------------------------

    @chronometre
    def inserer_transactions(
        self, transactions: Iterable[Transaction], taille_lot: int = 5_000
    ) -> int:
        """Insère (ou remplace) des transactions par lots de ``taille_lot``.

        Returns:
            Le nombre de transactions écrites.
        """
        if not isinstance(taille_lot, int) or taille_lot <= 0:
            raise ParametreInvalide("taille_lot doit être un entier > 0")
        total = 0
        flux = iter(transactions)
        try:
            with self.connexion:  # transaction SQLite : commit ou rollback automatique
                while lot := [_ligne_transaction(t) for t in islice(flux, taille_lot)]:
                    self.connexion.executemany(_INSERTION_TRANSACTION, lot)
                    total += len(lot)
        except sqlite3.Error as erreur:
            raise DepotError(f"Échec de l'insertion des transactions : {erreur}") from erreur
        journal.info("%d transactions enregistrées dans %s", total, self._chemin)
        return total

    def inserer_comptes(self, comptes: Iterable[Compte]) -> int:
        """Enregistre l'état courant des comptes (insertion ou remplacement)."""
        lignes = [
            (
                c.id_compte,
                c.type_compte,
                c.titulaire.id_client,
                c.titulaire.nom,
                c.titulaire.telephone,
                c.solde,
                int(c.est_gele),
                c.date_ouverture.isoformat(timespec="seconds") if c.date_ouverture else None,
            )
            for c in comptes
        ]
        try:
            with self.connexion:
                self.connexion.executemany(
                    "INSERT OR REPLACE INTO comptes (id_compte, type_compte, id_client, nom, "
                    "telephone, solde, gele, date_ouverture) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                    lignes,
                )
        except sqlite3.Error as erreur:
            raise DepotError(f"Échec de l'insertion des comptes : {erreur}") from erreur
        return len(lignes)

    def inserer_alertes(self, alertes: Iterable[Alerte]) -> int:
        """Enregistre des alertes du moteur de détection."""
        maintenant = datetime.now().isoformat(timespec="seconds")
        lignes = [
            (
                a.transaction.id_transaction,
                a.score,
                json.dumps(list(a.regles)),
                json.dumps(list(a.motifs), ensure_ascii=False),
                maintenant,
            )
            for a in alertes
        ]
        try:
            with self.connexion:
                self.connexion.executemany(
                    "INSERT OR REPLACE INTO alertes (id_transaction, "
                    "score, regles, motifs, detectee_le) "
                    "VALUES (?, ?, ?, ?, ?)",
                    lignes,
                )
        except sqlite3.Error as erreur:
            raise DepotError(f"Échec de l'insertion des alertes : {erreur}") from erreur
        return len(lignes)

    def vider(self) -> None:
        """Supprime toutes les données (le schéma est conservé)."""
        with self.connexion:
            for table in ("alertes", "transactions", "comptes"):
                self.connexion.execute(
                    f"DELETE FROM {table}"
                )  # noms de tables fixes, non issus d'une saisie

    # -- lecture ---------------------------------------------------------

    def compter_transactions(self, type_transaction: TypeTransaction | str | None = None) -> int:
        """Nombre de transactions, éventuellement d'un seul type."""
        if type_transaction is None:
            curseur = self.connexion.execute("SELECT COUNT(*) FROM transactions")
        else:
            curseur = self.connexion.execute(
                "SELECT COUNT(*) FROM transactions WHERE type = ?", (str(type_transaction),)
            )
        return int(curseur.fetchone()[0])

    def transactions(
        self,
        *,
        id_compte: str | None = None,
        debut: datetime | None = None,
        fin: datetime | None = None,
        type_transaction: TypeTransaction | str | None = None,
    ) -> Iterator[Transaction]:
        """Générateur des transactions (ordre chronologique), avec filtres facultatifs.

        Args:
            id_compte: ne garder que les transactions émises **ou** reçues par ce compte.
            debut: borne inférieure incluse sur l'horodatage.
            fin: borne supérieure exclue sur l'horodatage.
            type_transaction: ne garder qu'un type d'opération.
        """
        conditions: list[str] = []
        parametres: list[Any] = []
        if id_compte is not None:
            conditions.append("(id_emetteur = ? OR id_destinataire = ?)")
            parametres += [id_compte, id_compte]
        if debut is not None:
            conditions.append("horodatage >= ?")
            parametres.append(debut.isoformat(timespec="seconds"))
        if fin is not None:
            conditions.append("horodatage < ?")
            parametres.append(fin.isoformat(timespec="seconds"))
        if type_transaction is not None:
            conditions.append("type = ?")
            parametres.append(str(type_transaction))
        clause = f" WHERE {' AND '.join(conditions)}" if conditions else ""
        requete = (
            f"SELECT {_COLONNES_SELECTION} FROM transactions{clause} "
            "ORDER BY horodatage, id_transaction"
        )
        for ligne in self.connexion.execute(requete, parametres):
            yield _vers_transaction(ligne)

    def obtenir_transaction(self, id_transaction: str) -> Transaction | None:
        """Transaction d'identifiant donné, ou ``None``."""
        ligne = self.connexion.execute(
            f"SELECT {_COLONNES_SELECTION} FROM transactions WHERE id_transaction = ?",
            (id_transaction,),
        ).fetchone()
        return None if ligne is None else _vers_transaction(ligne)

    def statistiques_par_type(self) -> dict[str, dict[str, float]]:
        """Nombre, volume et taux de fraude par type d'opération (agrégation SQL)."""
        curseur = self.connexion.execute(
            "SELECT type, COUNT(*), SUM(montant), AVG(est_fraude) "
            "FROM transactions GROUP BY type ORDER BY type"
        )
        return {
            type_op: {
                "nombre": n,
                "volume": volume,
                "taux_fraude": taux if taux is not None else float("nan"),
            }
            for type_op, n, volume, taux in curseur
        }

    def solde_comptes(self) -> dict[str, int]:
        """Soldes enregistrés dans la table ``comptes``."""
        return dict(
            self.connexion.execute("SELECT id_compte, solde FROM comptes ORDER BY id_compte")
        )

    def alertes(self) -> list[dict[str, Any]]:
        """Alertes enregistrées, de la plus forte à la plus faible."""
        curseur = self.connexion.execute(
            "SELECT id_transaction, score, regles, motifs, detectee_le "
            "FROM alertes ORDER BY score DESC, id_transaction"
        )
        return [
            {
                "id_transaction": i,
                "score": s,
                "regles": json.loads(r),
                "motifs": json.loads(m),
                "detectee_le": d,
            }
            for i, s, r, m, d in curseur
        ]

    def lire_dataframe(self) -> pd.DataFrame:
        """Toutes les transactions sous forme de DataFrame (horodatage en ``datetime64``)."""
        import pandas as pd

        df = pd.read_sql_query(
            f"SELECT {_COLONNES_SELECTION} FROM transactions ORDER BY horodatage, id_transaction",
            self.connexion,
        )
        df["horodatage"] = pd.to_datetime(df["horodatage"], format="ISO8601")
        return df
