"""Permet ``python -m payguard ...`` en plus de la commande ``payguard``."""

from payguard.cli import main

raise SystemExit(main())
