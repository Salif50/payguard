"""Phase 5 — moteur de détection de fraude par règles métier (sans apprentissage automatique)."""

from payguard.detection.alerte import Alerte, Evaluation
from payguard.detection.base import Regle, ResultatRegle
from payguard.detection.configuration import (
    ConfigurationMoteur,
    charger_configuration,
    configuration_par_defaut,
)
from payguard.detection.evaluation import MatriceConfusion, RapportEvaluation, evaluer
from payguard.detection.moteur import MoteurDeRegles
from payguard.detection.regles import (
    RegleChangementZone,
    RegleCompteRecentVide,
    RegleHoraireInhabituel,
    RegleMontantAnormal,
    RegleMontantEleve,
    RegleNouvelAppareil,
    RegleRafale,
)

__all__ = [
    "Alerte",
    "ConfigurationMoteur",
    "Evaluation",
    "MatriceConfusion",
    "MoteurDeRegles",
    "RapportEvaluation",
    "Regle",
    "RegleChangementZone",
    "RegleCompteRecentVide",
    "RegleHoraireInhabituel",
    "RegleMontantAnormal",
    "RegleMontantEleve",
    "RegleNouvelAppareil",
    "RegleRafale",
    "ResultatRegle",
    "charger_configuration",
    "configuration_par_defaut",
    "evaluer",
]
