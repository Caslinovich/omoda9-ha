"""Registro unico dei timer del coordinator (P2-4).

**Il problema che risolve.** Il coordinator programma cinque timer ricorrenti
(keep-alive sessione, poll telemetria, follow-up alta tensione/ricarica, sonda iniziale,
battito di rilevamento marcia). Erano cinque attributi `_*_unsub` cancellati in tre punti
diversi e ri-armati in altri due. La conseguenza non era teorica:

* una lettura già "in volo" quando l'integrazione veniva scaricata tornava DOPO lo stop e
  ri-armava il follow-up → il ciclo continuava a interrogare il cloud per ore, a
  integrazione spenta (P0-4);
* spegnendo «Aggiornamento automatico» durante una ricarica restava attivo proprio il
  ciclo più frequente, quello a 2 minuti (P0-5).

Nessuno dei due dava errori nel log. Il costo era reale ma invisibile: consumo della
batteria 12V dell'auto e contesa con l'app ufficiale, che sul cloud Chery ammette **una
sola sessione per account** — quando il componente parla, l'app dell'utente viene
disconnessa.

**L'invariante, in un posto solo.** Dopo `close()` nessun timer può più essere armato:
`arm()` lo rifiuta. Non serve che i cinque punti che programmano timer si ricordino di
controllare un flag — è il registro a garantirlo. Le guardie sparse diventano superflue.

`arm()` riceve una *factory* e non un unsub già creato: così, a registro chiuso, il timer
non viene nemmeno programmato. Passando l'unsub si sarebbe creato il timer per poi
buttarlo via, lasciando una callback comunque schedulata nel frattempo.
"""
from __future__ import annotations

import logging
from collections.abc import Callable

_LOGGER = logging.getLogger(__name__)

# Nomi dei timer. Costanti e non stringhe sparse: un refuso in un `cancel("hv_pol")`
# fallirebbe in silenzio lasciando il timer armato — cioè il bug di partenza.
KEEPALIVE = "keepalive"          # refresh periodico della sessione (token)
POLL = "poll"                    # poll telemetria periodico (può SVEGLIARE l'auto)
HV_POLL = "hv_poll"              # follow-up ravvicinato ad alta tensione accesa / in carica
STARTUP_PROBE = "startup_probe"  # sonda one-shot ~15s dopo l'avvio (semina il follow-up)
DRIVE_WATCH = "drive_watch"      # battito di rilevamento marcia (sola lettura)

# Timer legati all'interruttore «Aggiornamento automatico»: si spengono TUTTI insieme.
# Il keep-alive NON è del gruppo — tiene viva la sessione (nessun contatto con l'auto) e
# deve continuare anche a poll spento, altrimenti il token scadrebbe e l'utente si
# ritroverebbe a rifare un OTP senza motivo.
GRUPPO_POLL = (POLL, HV_POLL, STARTUP_PROBE, DRIVE_WATCH)


class TimerRegistry:
    """Tiene gli `unsub` dei timer e garantisce che dopo `close()` non se ne armino altri."""

    def __init__(self) -> None:
        self._unsubs: dict[str, Callable[[], None]] = {}
        self._closing = False

    @property
    def closing(self) -> bool:
        """True dopo `close()`: l'integrazione si sta scaricando, punto di non ritorno."""
        return self._closing

    def arm(self, nome: str, factory: Callable[[], Callable[[], None]]) -> bool:
        """Programma il timer `nome` (sostituendo il precedente). False se il registro è chiuso.

        Idempotente per nome: ri-armare un timer già attivo cancella il vecchio invece di
        lasciarne due in volo — con un timer auto-rischedulante come il follow-up HV, due
        copie raddoppierebbero le letture al cloud a ogni giro."""
        if self._closing:
            _LOGGER.debug("[timer] %s non armato: registro chiuso", nome)
            return False
        self.cancel(nome)
        self._unsubs[nome] = factory()
        return True

    def cancel(self, nome: str) -> bool:
        """Cancella il timer `nome`. True se era davvero armato."""
        unsub = self._unsubs.pop(nome, None)
        if unsub is None:
            return False
        try:
            unsub()
        except Exception as err:  # noqa: BLE001 — un unsub che protesta non deve bloccare il teardown
            _LOGGER.debug("[timer] errore cancellando %s: %s", nome, err)
        return True

    def cancel_many(self, nomi) -> None:
        for nome in nomi:
            self.cancel(nome)

    def cancel_all(self) -> None:
        for nome in list(self._unsubs):
            self.cancel(nome)

    def close(self) -> None:
        """Teardown definitivo: cancella tutto e vieta ogni futuro `arm()`.

        Da qui non si torna indietro nemmeno se una chiamata già in volo prova a
        ri-armare al ritorno: è esattamente il poll orfano di P0-4."""
        self._closing = True
        self.cancel_all()

    # ───────────────────────── interrogazione (usata dai test) ─────────────────────────
    def is_armed(self, nome: str) -> bool:
        return nome in self._unsubs

    def armed(self) -> set[str]:
        """I nomi dei timer attualmente armati."""
        return set(self._unsubs)
