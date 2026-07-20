"""Anti-lockout del PIN: la parte che, sbagliata, blocca l'ACCOUNT REALE di Chery.

Contesto (audit 2026-07-19, P0-1): ogni checkPassword fallito incrementa gli errori PIN
lato Chery; superata la soglia l'account si blocca — e il blocco NON si risolve da Home
Assistant. Perciò il componente si auto-limita dopo `_PIN_FAIL_MAX` tentativi.

Il bug era che la guardia non era atomica: due thread (fallback di `_wake` + comando
dalla UI, o doppio "Sveglia") leggevano il contatore PRIMA che l'altro lo incrementasse,
superavano entrambi la guardia e mandavano DUE checkPassword con lo stesso PIN errato.

Questi test bloccano il comportamento corretto in modo che il refactor P2-3
(incapsulamento con lock interno) non possa reintrodurre la corsa.
"""
from __future__ import annotations

import threading

import pytest

import fixtures as FX


def _fail_pin(cloud, code: str = "A00285", delay: float = 0.0):
    """checkPassword che rifiuta: nessun taskId, col codice di PIN errato."""
    cloud.on("/tsp/v1/app/cpm/checkPassword",
             {"code": code, "message": "password error"}, delay=delay)


def test_pin_errato_conta_e_poi_blocca(core, cloud, ctx):
    """Dopo `_PIN_FAIL_MAX` rifiuti il conio si ferma DA SOLO: il backend non viene
    più interrogato. È la protezione del blocco account, e va verificata contando le
    chiamate reali, non solo l'eccezione."""
    commands = core["commands"]
    _fail_pin(cloud)

    for _ in range(ctx.lockout.max_fail):
        with pytest.raises(commands.CommandError) as err:
            commands._mint_taskid(ctx, FX.TUSERID)
        assert err.value.reason == "pin"

    chiamate_prima = cloud.count("checkPassword")
    assert chiamate_prima == ctx.lockout.max_fail

    # oltre la soglia: fallisce SENZA interrogare il backend
    with pytest.raises(commands.CommandError) as err:
        commands._mint_taskid(ctx, FX.TUSERID)
    assert err.value.reason == "pin"
    assert "bloccato" in str(err.value)
    assert cloud.count("checkPassword") == chiamate_prima, \
        "l'anti-lockout ha comunque contattato il backend: tentativo bruciato"


def test_conii_concorrenti_non_superano_la_soglia(core, cloud, ctx):
    """P0-1: la corsa vera. Molti thread coniano INSIEME con un PIN errato; il numero
    di checkPassword davvero inviati non deve mai superare la soglia.

    Senza il lock (o con un lock che non copre la POST) i thread superano tutti la
    guardia e il conteggio esplode → è così che si bruciano i tentativi dell'account.

    La `delay` sul finto backend NON è cosmetica: è ciò che rende il test capace di
    fallire. Con una risposta istantanea ogni thread completa prima che il successivo
    entri, la corsa non si riproduce e il test passa anche col lock rimosso (verificato).
    Con 50 ms — un decimo di una POST vera — senza lock passano tutti e 8."""
    commands = core["commands"]
    _fail_pin(cloud, delay=0.05)

    partenza = threading.Barrier(8)
    errori: list[Exception] = []

    def conia():
        partenza.wait()          # massimizza la sovrapposizione
        try:
            commands._mint_taskid(ctx, FX.TUSERID)
        except Exception as err:  # noqa: BLE001 — l'esito lo verifica il conteggio
            errori.append(err)

    thread = [threading.Thread(target=conia) for _ in range(8)]
    for t in thread:
        t.start()
    for t in thread:
        t.join(timeout=30)

    assert len(errori) == 8, "nessun conio doveva riuscire col PIN errato"
    assert cloud.count("checkPassword") <= ctx.lockout.max_fail, (
        f"inviati {cloud.count('checkPassword')} checkPassword con soglia "
        f"{ctx.lockout.max_fail}: la guardia non è atomica (corsa P0-1)"
    )


def test_successo_azzera_il_contatore(core, cloud, ctx):
    """Un conio riuscito riparte da zero: un PIN corretto dopo un errore isolato non
    deve restare a mezzo passo dal blocco."""
    commands = core["commands"]
    _fail_pin(cloud)
    with pytest.raises(commands.CommandError):
        commands._mint_taskid(ctx, FX.TUSERID)
    assert ctx.lockout.tentativi_falliti == 1

    cloud.on("/tsp/v1/app/cpm/checkPassword", data={"taskId": FX.TASKID})
    assert commands._mint_taskid(ctx, FX.TUSERID) == FX.TASKID
    assert ctx.lockout.tentativi_falliti == 0


def test_reset_lockout_sblocca_subito(core, cloud, ctx):
    """P0-2: l'utente riconfigura il PIN → `reset_pin_lockout()` deve sbloccare SUBITO,
    anche se reinserisce lo STESSO PIN (caso reale: il blocco non era colpa del PIN).
    Senza questo l'utente resta bloccato in silenzio fino allo scadere della finestra."""
    commands = core["commands"]
    _fail_pin(cloud)
    for _ in range(ctx.lockout.max_fail):
        with pytest.raises(commands.CommandError):
            commands._mint_taskid(ctx, FX.TUSERID)

    commands.reset_pin_lockout(ctx)
    cloud.on("/tsp/v1/app/cpm/checkPassword", data={"taskId": FX.TASKID})
    assert commands._mint_taskid(ctx, FX.TUSERID) == FX.TASKID


def test_pin_vuoto_non_interroga_il_backend(core, cloud, ctx):
    """PIN non configurato: si fallisce SUBITO, senza spendere un tentativo lato Chery."""
    commands = core["commands"]
    ctx.pin = ""
    with pytest.raises(commands.CommandError) as err:
        commands._mint_taskid(ctx, FX.TUSERID)
    assert err.value.reason == "pin"
    assert cloud.count("checkPassword") == 0


def test_pin_non_compare_mai_nella_richiesta_in_chiaro(core, cloud, ctx):
    """Il PIN viaggia cifrato (md5 + SM4): non deve mai apparire in chiaro nel body."""
    commands = core["commands"]
    commands._mint_taskid(ctx, FX.TUSERID)
    corpo = cloud.calls_to("checkPassword")[0]["body"]
    assert FX.PIN not in str(corpo), "PIN in chiaro nella richiesta checkPassword"
    assert corpo["password"] != FX.PIN
