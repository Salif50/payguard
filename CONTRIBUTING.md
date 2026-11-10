# Contribuer à PayGuard

Merci de votre intérêt pour PayGuard. Ce dépôt est d'abord un projet académique (Master 1 IASD) : les
contributions extérieures sont bienvenues, mais elles doivent respecter les contraintes du sujet décrites
ci-dessous.

## Signaler un problème

Ouvrez une *issue* en indiquant :

- la commande lancée (par exemple `payguard detecter fichier.csv`) et la sortie obtenue ;
- votre version de Python (`python --version`) et de PayGuard (`payguard --version`) ;
- si possible, un petit fichier CSV qui reproduit le problème (données fictives uniquement).

## Préparer l'environnement

```bash
git clone https://github.com/Salif50/payguard.git
cd payguard
python3 -m venv .venv
source .venv/bin/activate          # Windows : .venv\Scripts\activate
pip install -e ".[dev]"
pytest                             # tous les tests doivent passer
```

## Règles du projet

Ces règles viennent du sujet ; une contribution qui ne les respecte pas ne pourra pas être acceptée.

- **Bibliothèques autorisées** : bibliothèque standard, pandas, Matplotlib, pytest, pytest-cov. Pas de
  scikit-learn ni d'autre bibliothèque d'apprentissage automatique, pas de nouvelle dépendance.
- **Phases 1 à 3** (`generation/`, `comptes/`, `outils/`) : bibliothèque standard uniquement.
- **Reproductibilité** : tout tirage aléatoire passe par une instance `random.Random(graine)`.
- **Aucune requête SQL** en dehors de `src/payguard/donnees/depot.py`.
- **Le moteur de détection ne lit jamais `est_fraude`** : l'étiquette sert uniquement à l'évaluation.
- **Journalisation** avec `logging` ; `print` est réservé à l'affichage des résultats par la CLI.

## Style de code

- PEP 8, lignes de 99 caractères au plus (vérifiable avec `pycodestyle --max-line-length=99`).
- Annotations de types sur les interfaces publiques et docstrings, en français comme le reste du code.
- Exceptions métier : héritez de `PayGuardError` (`src/payguard/exceptions.py`).

## Ajouter une règle de détection

Le moteur suit le patron Stratégie : il ne faut pas le modifier.

1. Écrivez une sous-classe de `Regle` dans `src/payguard/detection/regles.py`, avec un attribut de classe
   `nom` et une méthode `evaluer(transaction, profil)`. Elle s'enregistre automatiquement.
2. Validez ses paramètres dans le constructeur avec `valider_nombre`.
3. Ajoutez-la à `config/regles.json` si elle doit être active par défaut.
4. Testez au moins un cas où elle se déclenche, un cas où elle ne se déclenche pas et un paramètre invalide.
5. Mesurez l'effet sur le coût avec `payguard evaluer` et indiquez le résultat dans la *pull request*.

## Proposer une modification

1. Créez une branche à partir de `main` (`git switch -c correction-xyz`).
2. Ajoutez ou mettez à jour les tests ; la couverture des paquets `comptes` et `detection` doit rester
   d'au moins 70 %.
3. Vérifiez avant d'envoyer :
   ```bash
   pytest --cov=payguard
   payguard simuler && payguard evaluer
   ```
4. Écrivez des messages de commit courts et explicites, en français.
5. Ouvrez une *pull request* qui explique le pourquoi de la modification.

Si votre modification change le générateur ou les règles, les chiffres du README et de `rapport/` ne sont
plus à jour : régénérez `rapport/resultats/` et corrigez les valeurs citées. Aucun résultat ne doit être
écrit sans avoir été mesuré.

## Licence

En contribuant, vous acceptez que votre contribution soit publiée sous la licence MIT du projet
(fichier [LICENSE](LICENSE)).
