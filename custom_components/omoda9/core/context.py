#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""`CoreCtx` — configurazione e stato di UN veicolo, passati esplicitamente (P2-6 / A1).

**Da dove veniamo.** I moduli `core/` leggevano la configurazione da variabili globali di
modulo, popolate a import-time da `os.environ` e riscritte prima di ogni chiamata da un
metodo del coordinator (`_bind_core`). Era la radice comune di sei bug confermati e di
tre limiti strutturali:

* **stato di processo condiviso** — VIN, PIN, token-path vivevano una volta sola per
  processo Home Assistant. Con due veicoli configurati il secondo entry sovrascriveva la
  configurazione del primo, e un comando poteva partire verso l'auto sbagliata;
* **finestre di incoerenza** — fra `_bind_core` e l'uso effettivo dei valori girava
  codice in thread executor: un reload dell'entry nel mezzo lasciava mezzo modulo
  configurato col vecchio account;
* **segreti nell'ambiente** — PIN ed email finivano in `os.environ`, leggibile da
  qualunque cosa giri dentro Home Assistant (altre integrazioni, template, add-on con
  accesso a `/proc`);
* **impossibilità di testare in parallelo** — due test non potevano usare due
  configurazioni diverse nello stesso processo.

**Dove andiamo.** Un `CoreCtx` per veicolo, creato dal coordinator e passato come primo
argomento a ogni funzione di `core/`. Niente più global mutabili, niente più `os.environ`.

**Perché il contesto contiene anche STATO e non solo configurazione.** Anti-lockout del
PIN, cache del taskId, cooldown della sveglia e della sonda sono tutti *per-veicolo*.
Finché stavano in global di modulo, con due auto configurate gli errori PIN dell'una
avrebbero bloccato i comandi dell'altra, e il taskId coniato per una sarebbe stato usato
per l'altra. Legarli al contesto risolve la cosa per costruzione.

`os.environ` resta usato in un solo punto legittimo: l'ambiente **effimero** dei
sottoprocessi di login (`login_omoda.py`, `prova_token.py`), che sono processi separati e
per i quali l'environment è l'unico canale sensato — vedi `session._subenv`.
"""
from __future__ import annotations

import os
import threading
from dataclasses import dataclass, field

from .pin_lockout import PinLockout

HERE = os.path.dirname(os.path.abspath(__file__))

# Default di REGIONE (Europa). Non sono segreti: sono endpoint pubblici Omoda/Chery.
DEFAULT_BFF = "https://legend-oj.omodaauto.nl/api"
DEFAULT_TSP_HOST = "https://tspconsole-eu.cheryinternational.com"
DEFAULT_CHANNEL_ID = "1"
DEFAULT_COUNTRY_ID = "1"
DEFAULT_TENANT_CODE = "300006"


@dataclass
class _StatoVeicolo:
    """Stato mutabile che appartiene a UN veicolo (non è configurazione).

    Tutto ciò che qui dentro fosse globale di modulo diventerebbe, con due auto
    configurate, una interferenza fra account diversi."""

    # anti-lockout del PIN: soglia e finestra sono per-account (vedi pin_lockout.py)
    lockout: PinLockout = field(default_factory=PinLockout)
    # taskId in cache: coniarlo costa un giro di checkPassword (la parte lenta di ogni
    # comando), ma è legato al PIN e al VIN → non è condivisibile fra veicoli.
    taskid: str | None = None
    taskid_ts: float = 0.0
    # cooldown della sveglia SMS (rate-limit reale lato Chery) e della sonda realtime
    ultimo_sms_ts: float = 0.0
    ultima_sonda_ts: float = 0.0
    # "una alla volta" per veicolo: due auto possono svegliarsi/sondare in parallelo
    lock_sveglia: threading.Lock = field(default_factory=threading.Lock)
    lock_sonda: threading.Lock = field(default_factory=threading.Lock)
    # serializza il refresh del token: Chery ruota il refresh_token a ogni uso, due
    # rinnovi in parallelo sullo STESSO file invaliderebbero la sessione.
    lock_token: threading.Lock = field(default_factory=threading.Lock)


@dataclass
class CoreCtx:
    """Tutto ciò che serve a `core/` per operare su un veicolo.

    Si costruisce una volta per config entry (vedi `Omoda9Coordinator._build_ctx`) e si
    passa come primo argomento alle funzioni di `core/`.
    """

    # — identità dell'account/veicolo (per-account: mai valori di default) —
    vin: str = ""
    tuserid: str = ""
    pin: str = ""
    email: str = ""

    # — percorsi per-entry nella config dir di Home Assistant —
    token_path: str = ""
    taskid_file: str = ""
    # cartella dei sorgenti per i sottoprocessi di login (default: questo pacchetto)
    src_dir: str = HERE

    # — parametri di regione —
    tsp_host: str = DEFAULT_TSP_HOST
    bff: str = DEFAULT_BFF
    channel_id: str = DEFAULT_CHANNEL_ID
    country_id: str = DEFAULT_COUNTRY_ID
    tenant_code: str = DEFAULT_TENANT_CODE

    # — comportamento —
    # conio automatico del taskId: senza, i comandi non possono partire (serve un
    # taskId benedetto da checkPassword). Disattivabile solo per diagnostica.
    mint_taskid: bool = True
    taskid_ttl: int = 600      # riuso del taskId in cache, in secondi
    # Monitor diagnostico (diag.py): callback impostata dal coordinator SOLO a monitor
    # acceso. `None` = dormiente, costo nullo. `core/` non conosce il coordinator.
    diag_hook: object | None = None

    # — stato per-veicolo —
    stato: _StatoVeicolo = field(default_factory=_StatoVeicolo)

    def __post_init__(self) -> None:
        # Percorsi di ripiego solo per uso da riga di comando/diagnostica: in Home
        # Assistant li valorizza sempre il coordinator (per-VIN, nella config dir).
        if not self.token_path:
            self.token_path = os.path.join(HERE, "token.json")
        if not self.taskid_file:
            self.taskid_file = os.path.join(HERE, "data", "taskid.txt")

    # ───────────────────────── comodità ─────────────────────────
    @property
    def lockout(self) -> PinLockout:
        return self.stato.lockout

    def diag(self, tipo: str, **campi) -> None:
        """Registra un evento diagnostico, se il monitor è acceso. Non deve MAI
        alterare il flusso: il monitor osserva, non partecipa."""
        hook = self.diag_hook
        if hook is None:
            return
        try:
            hook(tipo, **campi)
        except Exception:  # noqa: BLE001 — un monitor rotto non deve rompere un comando
            pass

    def invalidate_taskid(self) -> None:
        """Butta il taskId in cache (l'auto lo ha rifiutato o il PIN è cambiato)."""
        self.stato.taskid = None
        self.stato.taskid_ts = 0.0

    def reset_pin_lockout(self) -> None:
        """Azzera l'anti-lockout e il taskId: si usa quando l'utente riconfigura il PIN."""
        self.stato.lockout.reset()
        self.invalidate_taskid()


def ctx_da_environ() -> CoreCtx:
    """Contesto costruito da `os.environ` — SOLO per l'uso da riga di comando.

    I moduli `core/` si possono ancora lanciare a mano per diagnostica (`python -m …`)
    e in quel caso l'ambiente resta il modo più comodo per passare i parametri. Home
    Assistant NON passa mai di qui: il coordinator costruisce il contesto dal config
    entry, che è la sorgente di verità."""
    return CoreCtx(
        vin=os.environ.get("VIN", ""),
        tuserid=os.environ.get("TUSERID", ""),
        pin=os.environ.get("OMODA_PIN", ""),
        email=os.environ.get("OMODA_EMAIL", ""),
        token_path=os.environ.get("OMODA_TOKEN_PATH", ""),
        taskid_file=os.environ.get("OMODA_TASKID_FILE", ""),
        src_dir=os.environ.get("OMODA_SRC_DIR", HERE),
        tsp_host=os.environ.get("TSP_HOST", DEFAULT_TSP_HOST),
        bff=os.environ.get("OMODA_BFF", DEFAULT_BFF),
        channel_id=os.environ.get("CHANNEL_ID", DEFAULT_CHANNEL_ID),
        country_id=os.environ.get("OMODA_COUNTRY_ID", DEFAULT_COUNTRY_ID),
        tenant_code=os.environ.get("OMODA_TENANT_CODE", DEFAULT_TENANT_CODE),
        mint_taskid=os.environ.get("OMODA_MINT_TASKID", "1") not in ("0", "", "false", "no"),
    )
