#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Anti-lockout del PIN comandi — stato incapsulato, con lock interno (P2-3).

**Il rischio che questo modulo esiste per contenere.** Il PIN a 4 cifre dei comandi
remoti viene verificato dal backend Chery (`checkPassword`). Ogni verifica fallita
incrementa un contatore di errori LATO CHERY: superata la soglia, l'account viene
bloccato — e quel blocco non si risolve da Home Assistant. Perciò il componente si
auto-limita: dopo `max_fail` rifiuti consecutivi entro `window_s` smette di interrogare
il backend e chiede all'utente di riconfigurare il PIN.

**Perché una classe e non più un dizionario module-level.** Prima lo stato era
`_PIN_FAIL = {"n": 0, "ts": 0.0}` con un lock separato, e ogni chiamante doveva
ricordarsi di prendere il lock PRIMA di leggere il contatore e di tenerlo fino
all'aggiornamento. Bastava dimenticarsene una volta — o prendere il lock troppo tardi —
per riaprire la corsa P0-1: due thread leggevano il contatore prima che l'altro lo
incrementasse, superavano entrambi la guardia e mandavano due `checkPassword` con lo
stesso PIN errato.

Qui il lock non è opzionale: si entra solo da `attempt()`, che è un context manager e
serializza l'INTERO tentativo — guardia, chiamata di rete, aggiornamento del contatore.
Non esiste un modo di usare questa API che riapra la corsa. È la differenza fra «il bug
è stato corretto» e «il bug non è più rappresentabile».

**Nota per P2-6.** La classe è istanziabile di proposito: col contesto per-chiamata ogni
veicolo/account avrà la propria istanza, invece di condividere un contatore di processo
(oggi, con due auto configurate, gli errori dell'una bloccherebbero i comandi dell'altra).
"""
from __future__ import annotations

import contextlib
import threading
import time


class PinLockedError(Exception):
    """L'anti-lockout è scattato: NON si è contattato il backend.

    Distinta da un rifiuto vero del backend proprio perché qui nessun tentativo è
    stato speso lato Chery — è la protezione che ha funzionato, non un errore nuovo."""

    def __init__(self, tentativi: int, message: str | None = None) -> None:
        self.tentativi = tentativi
        super().__init__(message or f"PIN bloccato dopo {tentativi} tentativi errati")


class _Tentativo:
    """Esito di un singolo tentativo, dichiarato esplicitamente dal chiamante.

    Volutamente NON si deduce l'esito dall'eventuale eccezione: un errore di rete o un
    rifiuto per permessi del veicolo non sono un PIN errato e non devono avvicinare il
    blocco dell'account. Chi conia decide, caso per caso, se il tentativo è "colpa del PIN".
    """

    __slots__ = ("_esito",)

    def __init__(self) -> None:
        self._esito: str | None = None

    def riuscito(self) -> None:
        """taskId ottenuto → il contatore riparte da zero."""
        self._esito = "ok"

    def fallito(self) -> None:
        """Il backend ha rifiutato ED è imputabile al PIN → conta verso il blocco."""
        self._esito = "ko"


class PinLockout:
    """Contatore anti-lockout con lock interno.

    Uso::

        with lockout.attempt() as tentativo:      # solleva PinLockedError se bloccato
            risposta = chiama_backend()           # serializzata: un tentativo alla volta
            if risposta.taskid:
                tentativo.riuscito()
            elif e_colpa_del_pin(risposta):
                tentativo.fallito()
            # nessuna dichiarazione = il tentativo non conta (rete, permessi, sessione)
    """

    def __init__(self, max_fail: int = 2, window_s: int = 600) -> None:
        self.max_fail = max_fail
        self.window_s = window_s
        # RLock: `attempt()` può chiamare `reset()` senza autobloccarsi.
        self._lock = threading.RLock()
        self._n = 0
        self._ts = 0.0

    # ───────────────────────── interrogazione ─────────────────────────
    @property
    def tentativi_falliti(self) -> int:
        with self._lock:
            return self._n

    def is_locked(self) -> bool:
        """True se un nuovo tentativo verrebbe rifiutato senza contattare il backend."""
        with self._lock:
            return self._bloccato()

    def _bloccato(self) -> bool:
        """Da chiamare col lock già preso."""
        if self._n < self.max_fail:
            return False
        # la finestra è scorrevole: passati `window_s` dall'ultimo errore si riparte
        return (time.time() - self._ts) < self.window_s

    # ───────────────────────── mutazione ─────────────────────────
    def reset(self) -> None:
        """Azzera il blocco.

        Va chiamato quando l'utente compie un gesto esplicito di rimedio (riconfigura il
        PIN dal config flow o dal Repair) ANCHE se reinserisce lo stesso PIN: il blocco
        poteva non essere colpa del PIN, e senza reset l'utente resterebbe fermo — senza
        alcun segnale — fino allo scadere della finestra. Lo stato non è nel config entry,
        quindi un reload dell'integrazione da solo non lo azzera."""
        with self._lock:
            self._n = 0
            self._ts = 0.0

    @contextlib.contextmanager
    def attempt(self):
        """Serializza un tentativo e applica la guardia. Solleva `PinLockedError` se bloccato.

        Il lock resta preso per tutta la durata del blocco `with` — chiamata di rete
        inclusa. È intenzionale e non negoziabile: rilasciarlo prima della risposta
        riaprirebbe esattamente la corsa che questa classe esiste per chiudere."""
        with self._lock:
            if self._bloccato():
                raise PinLockedError(self._n)
            tentativo = _Tentativo()
            # `finally` NON è un dettaglio: il chiamante dichiara `fallito()` e subito dopo
            # SOLLEVA (CommandError con il rimedio per l'utente). Senza `finally` l'eccezione
            # scavalcherebbe l'aggiornamento del contatore e il blocco non scatterebbe mai —
            # cioè la protezione dell'account resterebbe silenziosamente disattivata.
            try:
                yield tentativo
            finally:
                if tentativo._esito == "ok":
                    self._n = 0
                    self._ts = 0.0
                elif tentativo._esito == "ko":
                    self._n += 1
                    self._ts = time.time()
