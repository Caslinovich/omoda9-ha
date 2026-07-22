"""`TimerRegistry` in isolamento (P2-4).

Il punto di questi test è dimostrare che l'invariante **non dipende più dalla disciplina
del chiamante**. Prima «non ri-armare dopo lo stop» era una regola che ognuno dei cinque
punti che programmano timer doveva ricordarsi di rispettare; bastava dimenticarla una
volta per lasciare un poll che interrogava il cloud per ore a integrazione spenta.
Ora la garanzia è del registro.
"""
from __future__ import annotations

from custom_components.omoda9.timers import GRUPPO_POLL, KEEPALIVE, POLL, TimerRegistry


def _finto_timer(tracker: list, nome: str):
    """Finta factory: registra la cancellazione, come farebbe un unsub di HA."""
    return lambda: (lambda: tracker.append(nome))


def test_arma_e_cancella():
    reg = TimerRegistry()
    cancellati: list = []
    reg.arm(POLL, _finto_timer(cancellati, POLL))
    assert reg.is_armed(POLL)

    assert reg.cancel(POLL) is True
    assert not reg.is_armed(POLL)
    assert cancellati == [POLL], "l'unsub non è stato invocato"


def test_riarmare_non_lascia_due_timer_in_volo():
    """Con un timer auto-rischedulante due copie raddoppierebbero le letture al cloud
    a ogni giro — e la seconda non sarebbe cancellabile, perché il registro ne
    conoscerebbe una sola."""
    reg = TimerRegistry()
    cancellati: list = []
    reg.arm(POLL, _finto_timer(cancellati, "primo"))
    reg.arm(POLL, _finto_timer(cancellati, "secondo"))

    assert cancellati == ["primo"], "il primo timer non è stato cancellato dal ri-arm"
    reg.cancel(POLL)
    assert cancellati == ["primo", "secondo"]


def test_dopo_close_non_si_arma_piu_nulla():
    """Il cuore di P2-4: la garanzia è del registro, non di chi chiama."""
    reg = TimerRegistry()
    creati: list = []

    def factory():
        creati.append(1)
        return lambda: None

    reg.close()
    assert reg.arm(POLL, factory) is False
    assert not reg.is_armed(POLL)
    assert creati == [], "a registro chiuso il timer non va nemmeno CREATO"


def test_close_cancella_tutto():
    reg = TimerRegistry()
    cancellati: list = []
    for nome in (KEEPALIVE, POLL):
        reg.arm(nome, _finto_timer(cancellati, nome))

    reg.close()
    assert reg.armed() == set()
    assert sorted(cancellati) == sorted([KEEPALIVE, POLL])
    assert reg.closing is True


def test_gruppo_poll_non_tocca_il_keepalive():
    """Spegnendo «Aggiornamento automatico» il keep-alive deve restare: tiene viva la
    sessione senza mai contattare l'auto. Fermarlo farebbe scadere il token e l'utente
    si vedrebbe chiedere un OTP senza alcun motivo."""
    reg = TimerRegistry()
    cancellati: list = []
    reg.arm(KEEPALIVE, _finto_timer(cancellati, KEEPALIVE))
    for nome in GRUPPO_POLL:
        reg.arm(nome, _finto_timer(cancellati, nome))

    reg.cancel_many(GRUPPO_POLL)

    assert reg.armed() == {KEEPALIVE}
    assert KEEPALIVE not in cancellati
    assert reg.closing is False, "spegnere il poll non è un teardown definitivo"


def test_il_gruppo_poll_copre_ogni_timer_che_contatta_il_cloud():
    """Guard-rail: un timer nuovo che parla col cloud e NON entra in `GRUPPO_POLL`
    sopravviverebbe allo switch OFF — è esattamente il bug P0-5."""
    from custom_components.omoda9 import timers

    # Le uniche due eccezioni ammesse, entrambe perché NON contattano nessuno:
    #   KEEPALIVE → parla col cloud ma NON con l'auto, e deve restare acceso a poll spento
    #               (altrimenti il token scade e l'utente si rifà un OTP per niente);
    #   AWAKE     → puro conto alla rovescia locale che fa scadere lo stato «auto sveglia».
    #               Spegnerlo col poll rimetterebbe il flag nella condizione in cui restava
    #               acceso per sempre, e il pulsante «Sveglia auto» tornerebbe inutilizzabile.
    senza_contatto = {KEEPALIVE, timers.AWAKE}
    tutti = {v for k, v in vars(timers).items()
             if k.isupper() and isinstance(v, str) and not k.startswith("_")}
    fuori_gruppo = tutti - set(GRUPPO_POLL)
    assert fuori_gruppo == senza_contatto, (
        f"timer fuori da GRUPPO_POLL: {fuori_gruppo}. Se contatta l'auto o il cloud "
        f"deve stare nel gruppo, altrimenti sopravvive allo switch «Aggiornamento "
        f"automatico» su OFF."
    )


def test_cancellare_un_timer_inesistente_e_innocuo():
    reg = TimerRegistry()
    assert reg.cancel("mai_armato") is False


def test_un_unsub_che_solleva_non_blocca_il_teardown():
    """Se un unsub protesta, gli altri timer devono comunque essere cancellati: un
    teardown a metà lascerebbe proprio i poll orfani che si vogliono evitare."""
    reg = TimerRegistry()
    cancellati: list = []

    def rotto():
        raise RuntimeError("unsub rotto")

    reg.arm("rotto", lambda: rotto)
    reg.arm(POLL, _finto_timer(cancellati, POLL))

    reg.close()
    assert reg.armed() == set()
    assert cancellati == [POLL], "il teardown si è fermato al primo unsub rotto"
