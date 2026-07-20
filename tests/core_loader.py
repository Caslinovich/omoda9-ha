"""Punto UNICO da cui i test prendono i moduli di `core/`.

Dopo P2-2 `core/` è un sotto-pacchetto vero: basta un import normale. Prima serviva
caricare ogni modulo dal file e fissarlo in `sys.modules` per nome nudo, perché i
moduli si importavano fra loro con nomi generici (`import wake`) e non erano
raggiungibili come `custom_components.omoda9.core.wake`.

L'indirezione resta perché è ciò che ha reso possibile il refactor: i test asseriscono
sul COMPORTAMENTO e hanno attraversato il cambio di meccanismo di import senza che una
sola asserzione venisse toccata — solo questo file.
"""
from __future__ import annotations

import os

_HERE = os.path.dirname(os.path.abspath(__file__))
CORE_DIR = os.path.join(_HERE, "..", "custom_components", "omoda9", "core")

_NOMI = (
    "codes", "omoda", "omoda_auth", "tsp_sign", "captcha_solver", "prova_token",
    "login_omoda", "wake", "session", "probe", "provision", "commands",
)


def load_core() -> dict:
    """Ritorna {nome: modulo} del sotto-pacchetto `core`.

    Python garantisce l'unicità dei moduli di pacchetto in `sys.modules`, quindi i
    monkeypatch dei test e il codice del componente vedono la STESSA istanza — cosa
    che prima del refactor andava ottenuta a mano (e si rompeva al reload dell'entry)."""
    import importlib

    out: dict = {}
    for nome in _NOMI:
        try:
            out[nome] = importlib.import_module(f"custom_components.omoda9.core.{nome}")
        except ImportError:
            continue
    return out
