"""La :class:`Plateforme` : compose les comptes et exécute les opérations de façon atomique."""

from __future__ import annotations

import logging
from collections import Counter
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import datetime
from typing import Any

from payguard.comptes.base import Compte
from payguard.comptes.registre import RegistreComptes
from payguard.comptes.transaction import Transaction, TypeTransaction
from payguard.exceptions import OperationNonAutorisee, PayGuardError
from payguard.outils.contextes import TransactionAtomique, transaction_atomique
from payguard.outils.decorateurs import journaliser

journal = logging.getLogger(__name__)

#: État capturé de la plateforme : (taille de l'historique, revenus, compteur d'identifiants).
EtatPlateforme = tuple[int, int, int]


class Plateforme:
    """Opérateur de paiement mobile : détient les comptes et l'historique des transactions.

    *Composition* : la plateforme **possède** un :class:`RegistreComptes` et
    une liste de :class:`Transaction` ; elle n'hérite d'aucun des deux.

    Toutes les opérations passent par :meth:`executer`, qui :

    1. résout les comptes et vérifie la cohérence (émetteur ≠ destinataire,
       types autorisés de part et d'autre) ;
    2. ouvre une :class:`~payguard.outils.contextes.TransactionAtomique` sur
       l'émetteur et le destinataire ;
    3. débite l'émetteur (montant + frais), crédite le destinataire ;
    4. n'enregistre la transaction et les frais qu'en cas de succès.

    Si l'une des deux jambes échoue, le gestionnaire de contexte restaure les
    deux comptes : l'état revient exactement à l'état initial.
    """

    def __init__(self, nom: str = "PayGuard", comptes: RegistreComptes | None = None) -> None:
        self.nom = nom
        self._comptes = comptes if comptes is not None else RegistreComptes()
        self._historique: list[Transaction] = []
        self._revenus = 0
        self._compteur = 0
        self.rejets: Counter[str] = Counter()

    # ------------------------------------------------------------------
    # Comptes
    # ------------------------------------------------------------------

    @property
    def comptes(self) -> RegistreComptes:
        """Registre des comptes ouverts sur la plateforme."""
        return self._comptes

    def ouvrir_compte(self, compte: Compte) -> Compte:
        """Enregistre un nouveau compte et le renvoie."""
        self._comptes.ajouter(compte)
        journal.debug("Compte ouvert : %r", compte)
        return compte

    def compte(self, id_compte: str) -> Compte:
        """Renvoie le compte ``id_compte`` (lève :class:`CompteIntrouvable`)."""
        return self._comptes.obtenir(id_compte)

    # ------------------------------------------------------------------
    # Opérations
    # ------------------------------------------------------------------

    @property
    def historique(self) -> tuple[Transaction, ...]:
        """Transactions exécutées avec succès, dans l'ordre d'exécution (copie immuable)."""
        return tuple(self._historique)

    @property
    def revenus(self) -> int:
        """Total des frais encaissés par la plateforme (GNF)."""
        return self._revenus

    def _nouvel_identifiant(self) -> str:
        self._compteur += 1
        return f"PG{self._compteur:08d}"

    @journaliser
    def executer(
        self,
        type_transaction: TypeTransaction | str,
        id_emetteur: str,
        id_destinataire: str,
        montant: int,
        *,
        horodatage: datetime | None = None,
        zone: str = "Conakry",
        appareil_id: str = "INCONNU",
        id_transaction: str | None = None,
        est_fraude: bool | None = None,
    ) -> Transaction:
        """Exécute une opération atomique et l'ajoute à l'historique.

        Returns:
            La :class:`Transaction` enregistrée.

        Raises:
            CompteIntrouvable, CompteGele, OperationNonAutorisee,
            PlafondDepasse, SoldeInsuffisant, ParametreInvalide.
        """
        type_tx = (
            type_transaction
            if isinstance(type_transaction, TypeTransaction)
            else TypeTransaction.depuis_texte(type_transaction)
        )
        instant = horodatage or datetime.now().replace(microsecond=0)
        try:
            emetteur = self._comptes.obtenir(id_emetteur)
            destinataire = self._comptes.obtenir(id_destinataire)
            if emetteur is destinataire:
                raise OperationNonAutorisee(
                    "L'émetteur et le destinataire doivent être différents"
                )
            if not destinataire.peut_recevoir(type_tx):
                raise OperationNonAutorisee(
                    f"Un compte {destinataire.type_compte} ne peut "
                    f"pas recevoir l'opération {type_tx.value}"
                )
            with TransactionAtomique(emetteur, destinataire):
                frais = emetteur.debiter(montant, type_tx, instant)
                destinataire.crediter(montant, type_tx)
                transaction = Transaction(
                    id_transaction=id_transaction or self._nouvel_identifiant(),
                    horodatage=instant,
                    id_emetteur=emetteur.id_compte,
                    id_destinataire=destinataire.id_compte,
                    type=type_tx,
                    montant=montant,
                    zone=zone,
                    appareil_id=appareil_id,
                    est_fraude=est_fraude,
                )
        except PayGuardError as erreur:
            self.rejets[type(erreur).__name__] += 1
            raise
        # Point de non-retour : les deux jambes ont réussi.
        self._revenus += frais
        self._historique.append(transaction)
        return transaction

    def deposer(self, id_agent: str, id_client: str, montant: int, **options: Any) -> Transaction:
        """Dépôt d'espèces : le compte de l'agent est débité au profit du client."""
        return self.executer(TypeTransaction.DEPOT, id_agent, id_client, montant, **options)

    def retirer(self, id_client: str, id_agent: str, montant: int, **options: Any) -> Transaction:
        """Retrait d'espèces : le client est débité au profit de l'agent."""
        return self.executer(TypeTransaction.RETRAIT, id_client, id_agent, montant, **options)

    def transferer(
        self, id_source: str, id_cible: str, montant: int, **options: Any
    ) -> Transaction:
        """Transfert entre deux comptes, atomique."""
        return self.executer(TypeTransaction.TRANSFERT, id_source, id_cible, montant, **options)

    def payer(self, id_client: str, id_marchand: str, montant: int, **options: Any) -> Transaction:
        """Paiement chez un commerçant."""
        return self.executer(
            TypeTransaction.PAIEMENT_MARCHAND, id_client, id_marchand, montant, **options
        )

    # ------------------------------------------------------------------
    # Atomicité de groupes d'opérations
    # ------------------------------------------------------------------

    def capturer_etat(self) -> EtatPlateforme:
        """Capture l'état propre de la plateforme (historique, revenus, compteur)."""
        return (len(self._historique), self._revenus, self._compteur)

    def restaurer_etat(self, etat: EtatPlateforme) -> None:
        """Restaure l'état propre de la plateforme."""
        taille, self._revenus, self._compteur = etat
        del self._historique[taille:]

    @contextmanager
    def operations_groupees(self, *ids_comptes: str) -> Iterator[Plateforme]:
        """Exécute plusieurs opérations en « tout ou rien ».

        Exemple : un paiement fractionné vers plusieurs commerçants doit soit
        réussir entièrement, soit ne laisser aucune trace ::

            with plateforme.operations_groupees("P1", "M1", "M2"):
                plateforme.payer("P1", "M1", 10_000)
                plateforme.payer("P1", "M2", 20_000)

        Args:
            ids_comptes: comptes concernés ; si aucun n'est donné, tous les
                comptes sont protégés (coût proportionnel au nombre de comptes).
        """
        participants: list[Any] = (
            [self._comptes.obtenir(i) for i in ids_comptes] if ids_comptes else list(self._comptes)
        )
        with transaction_atomique(self, *participants):
            yield self

    # ------------------------------------------------------------------
    # Méthodes spéciales et résumé
    # ------------------------------------------------------------------

    def statistiques(self) -> dict[str, Any]:
        """Résumé chiffré de l'état de la plateforme."""
        return {
            "nb_comptes": len(self._comptes),
            "nb_transactions": len(self._historique),
            "revenus": self._revenus,
            "masse_monetaire": self._comptes.solde_total,
            "rejets": dict(self.rejets),
            "par_type": dict(Counter(t.type.value for t in self._historique)),
        }

    def __len__(self) -> int:
        """Nombre de comptes ouverts."""
        return len(self._comptes)

    def __iter__(self) -> Iterator[Compte]:
        """Parcourt les comptes ouverts."""
        return iter(self._comptes)

    def __contains__(self, element: object) -> bool:
        """``"P000001" in plateforme`` ou ``compte in plateforme``."""
        return element in self._comptes

    def __repr__(self) -> str:
        return (
            f"Plateforme(nom={self.nom!r}, comptes={len(self._comptes)}, "
            f"transactions={len(self._historique)}, revenus={self._revenus})"
        )
