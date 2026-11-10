"""Titulaire d'un compte, avec attributs validés par des propriétés."""

from __future__ import annotations

import re

from payguard.exceptions import ParametreInvalide

#: Numéro mobile guinéen : indicatif +224 (facultatif) puis 9 chiffres commençant par 6.
_MOTIF_TELEPHONE = re.compile(r"^(?:\+224|00224|224)?(6\d{8})$")


def normaliser_telephone(numero: str) -> str:
    """Normalise un numéro mobile guinéen au format ``+2246XXXXXXXX``.

    Accepte les espaces, points, tirets et les préfixes ``+224``, ``00224``,
    ``224`` ou aucun préfixe.

    Raises:
        ParametreInvalide: si le numéro n'est pas un mobile guinéen valide.
    """
    if not isinstance(numero, str):
        raise ParametreInvalide(f"Le numéro de téléphone doit être une chaîne (reçu : {numero!r})")
    compact = re.sub(r"[\s.\-()]", "", numero)
    correspondance = _MOTIF_TELEPHONE.fullmatch(compact)
    if correspondance is None:
        raise ParametreInvalide(
            f"Numéro de téléphone guinéen invalide : {numero!r} "
            "(attendu : +224 suivi de 9 chiffres commençant par 6)"
        )
    return "+224" + correspondance.group(1)


class Client:
    """Personne physique ou morale titulaire d'un ou plusieurs comptes.

    Les attributs ``nom`` et ``telephone`` sont exposés par des propriétés :
    la validation a lieu à la construction *et* à chaque modification, si
    bien qu'un ``Client`` ne peut jamais se trouver dans un état invalide.
    """

    def __init__(self, id_client: str, nom: str, telephone: str) -> None:
        if not isinstance(id_client, str) or not id_client.strip():
            raise ParametreInvalide("L'identifiant client doit être une chaîne non vide")
        self._id_client = id_client.strip()
        self.nom = nom
        self.telephone = telephone

    @property
    def id_client(self) -> str:
        """Identifiant unique du client (lecture seule)."""
        return self._id_client

    @property
    def nom(self) -> str:
        """Nom complet, non vide, espaces superflus retirés."""
        return self._nom

    @nom.setter
    def nom(self, valeur: str) -> None:
        if not isinstance(valeur, str) or not valeur.strip():
            raise ParametreInvalide("Le nom du client ne peut pas être vide")
        self._nom = " ".join(valeur.split())

    @property
    def telephone(self) -> str:
        """Numéro mobile guinéen normalisé (``+2246XXXXXXXX``)."""
        return self._telephone

    @telephone.setter
    def telephone(self, valeur: str) -> None:
        self._telephone = normaliser_telephone(valeur)

    @property
    def telephone_affichage(self) -> str:
        """Numéro lisible : ``+224 6XX XX XX XX``."""
        n = self._telephone[4:]
        return f"+224 {n[:3]} {n[3:5]} {n[5:7]} {n[7:]}"

    def __repr__(self) -> str:
        return (
            f"Client(id_client={self._id_client!r}, nom={self._nom!r}, "
            f"telephone={self._telephone!r})"
        )

    def __eq__(self, autre: object) -> bool:
        if not isinstance(autre, Client):
            return NotImplemented
        return self._id_client == autre._id_client

    def __hash__(self) -> int:
        return hash(self._id_client)
