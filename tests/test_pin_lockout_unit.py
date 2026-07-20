"""`PinLockout` in isolamento (P2-3) — la classe, senza rete né Home Assistant.

I test in `test_pin_lockout.py` verificano il comportamento attraverso `commands`, cioè
come lo vive l'utente. Questi verificano il contratto della classe: sono più veloci,
falliscono in modo più preciso e — soprattutto — descrivono l'API che P2-6 userà per
dare a ogni veicolo il proprio contatore.
"""
from __future__ import annotations

import threading
import time

import pytest

from custom_components.omoda9.core.pin_lockout import PinLockedError, PinLockout


def test_parte_sbloccato():
    assert PinLockout().is_locked() is False


def test_si_blocca_alla_soglia():
    lockout = PinLockout(max_fail=2, window_s=600)
    for _ in range(2):
        with lockout.attempt() as t:
            t.fallito()
    assert lockout.is_locked() is True
    with pytest.raises(PinLockedError):
        with lockout.attempt():
            pytest.fail("il corpo non doveva nemmeno essere eseguito")


def test_il_successo_azzera():
    lockout = PinLockout(max_fail=2)
    with lockout.attempt() as t:
        t.fallito()
    with lockout.attempt() as t:
        t.riuscito()
    assert lockout.tentativi_falliti == 0
    assert lockout.is_locked() is False


def test_tentativo_non_dichiarato_non_conta():
    """Il caso che protegge l'account: errori di rete, permessi veicolo e sessione
    scaduta NON sono PIN errati e non devono avvicinare il blocco."""
    lockout = PinLockout(max_fail=2)
    for _ in range(10):
        with lockout.attempt():
            pass          # nessuna dichiarazione = non attribuibile al PIN
    assert lockout.tentativi_falliti == 0
    assert lockout.is_locked() is False


def test_fallimento_conta_anche_se_il_chiamante_solleva():
    """Regressione reale, colta dalla suite durante lo sviluppo di P2-3.

    Chi conia dichiara `fallito()` e subito dopo SOLLEVA (`CommandError` col rimedio da
    mostrare all'utente). Se l'aggiornamento del contatore non è in un `finally`,
    l'eccezione lo scavalca: il conteggio resta a zero, il blocco non scatta mai e la
    protezione dell'account è disattivata **senza alcun sintomo visibile** — i comandi
    continuano a funzionare, semplicemente non ci si ferma più prima del blocco Chery."""
    lockout = PinLockout(max_fail=2)

    for _ in range(2):
        with pytest.raises(ValueError):
            with lockout.attempt() as t:
                t.fallito()
                raise ValueError("il backend ha rifiutato: PIN errato")

    assert lockout.tentativi_falliti == 2
    assert lockout.is_locked() is True


def test_la_finestra_scorre():
    """Passata la finestra si riparte da capo: il blocco è temporaneo, non definitivo."""
    lockout = PinLockout(max_fail=1, window_s=600)
    with lockout.attempt() as t:
        t.fallito()
    assert lockout.is_locked() is True

    lockout._ts = time.time() - 601      # simula il tempo trascorso
    assert lockout.is_locked() is False


def test_reset_sblocca():
    lockout = PinLockout(max_fail=1)
    with lockout.attempt() as t:
        t.fallito()
    lockout.reset()
    assert lockout.is_locked() is False


def test_un_eccezione_nel_corpo_non_lascia_il_lock_preso():
    """Se il codice dentro `attempt()` solleva (es. rete giù), il lock va comunque
    rilasciato — altrimenti ogni comando successivo resterebbe appeso per sempre."""
    lockout = PinLockout()
    with pytest.raises(RuntimeError):
        with lockout.attempt():
            raise RuntimeError("rete giù")

    completato = threading.Event()

    def riprova():
        with lockout.attempt():
            completato.set()

    t = threading.Thread(target=riprova)
    t.start()
    t.join(timeout=5)
    assert completato.is_set(), "lock non rilasciato dopo un'eccezione: deadlock"


def test_i_tentativi_sono_serializzati():
    """Il cuore di P2-3: due tentativi non possono MAI sovrapporsi. Se si sovrapponessero,
    entrambi supererebbero la guardia e manderebbero un checkPassword ciascuno."""
    lockout = PinLockout(max_fail=99)      # soglia alta: qui si misura la mutua esclusione
    dentro = {"ora": 0, "max": 0}
    campanella = threading.Lock()

    def conia():
        with lockout.attempt():
            with campanella:
                dentro["ora"] += 1
                dentro["max"] = max(dentro["max"], dentro["ora"])
            time.sleep(0.02)               # finestra in cui un altro thread potrebbe entrare
            with campanella:
                dentro["ora"] -= 1

    thread = [threading.Thread(target=conia) for _ in range(8)]
    for t in thread:
        t.start()
    for t in thread:
        t.join(timeout=30)

    assert dentro["max"] == 1, (
        f"{dentro['max']} tentativi sovrapposti: la mutua esclusione non regge"
    )


def test_istanze_indipendenti():
    """Preparazione a P2-6 (multi-veicolo): il blocco di un'auto non deve fermare l'altra.

    Oggi il contatore è unico per processo, quindi con due auto configurate gli errori
    dell'una bloccherebbero i comandi dell'altra. La classe è già pronta; manca solo
    che il contesto per-chiamata le dia un'istanza per veicolo."""
    auto_a, auto_b = PinLockout(max_fail=1), PinLockout(max_fail=1)
    with auto_a.attempt() as t:
        t.fallito()
    assert auto_a.is_locked() is True
    assert auto_b.is_locked() is False
