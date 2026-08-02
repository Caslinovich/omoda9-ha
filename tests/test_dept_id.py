"""`DEPT-ID`: l'intestazione che diceva «Italia» a tutti.

Quel campo è, per ammissione della mappa da cui è stato estratto decompilando l'app, il
PREFISSO del Paese — Italia 39, Francia 33, Germania 49 — e restava inchiodato a `39` per
chiunque. Finché si entrava solo con l'e-mail il dato non esisteva nemmeno; con il login via
SMS il prefisso è diventato qualcosa che l'utente sceglie, e continuava a non arrivare qui.

⚠️ Nessuno di questi test dimostra che il server lo controlli: quello si può misurare solo con
un account registrato fuori dall'Italia. Dimostrano che il valore scelto dall'utente arriva
dove deve, e che per un account italiano non cambia assolutamente nulla.
"""
from __future__ import annotations

import pytest


def _auth(core):
    return core["omoda_auth"]


def test_senza_contesto_resta_il_default(core):
    A = _auth(core)
    assert A.headers_post("/x")["DEPT-ID"] == A.DEPT_ID


def test_il_contesto_porta_il_prefisso(core, ctx):
    A = _auth(core)
    ctx.area_code = "49"
    assert A.headers_post("/x", ctx=ctx)["DEPT-ID"] == "49"


def test_per_un_account_italiano_non_cambia_nulla(core, ctx):
    A = _auth(core)
    ctx.area_code = "39"
    assert A.headers_post("/x", ctx=ctx)["DEPT-ID"] == A.DEPT_ID


def test_un_contesto_senza_prefisso_ripiega_sul_default(core, ctx):
    """Gli account e-mail non hanno prefisso: non devono trovarsi un'intestazione vuota."""
    A = _auth(core)
    ctx.area_code = ""
    assert A.headers_post("/x", ctx=ctx)["DEPT-ID"] == A.DEPT_ID


def test_il_valore_esplicito_vince_sul_contesto(core, ctx):
    """Serve alla diagnostica: poter forzare il valore senza costruire un contesto finto."""
    A = _auth(core)
    ctx.area_code = "49"
    assert A.headers_post("/x", dept_id="33", ctx=ctx)["DEPT-ID"] == "33"


@pytest.mark.parametrize("scritto,atteso", [
    ("49", "49"), ("+49", "49"), ("0049", "49"), ("", None), (None, None), ("abc", None),
])
def test_il_sottoprocesso_ricava_il_prefisso_dal_valore_grezzo(core, scritto, atteso):
    """`prova_token` gira come sottoprocesso senza contesto e legge il prefisso dall'ambiente,
    dove arriva com'è stato scritto: la pulizia va rifatta qui, e un valore illeggibile deve
    lasciare il default invece di produrre un'intestazione senza senso."""
    PT = core["prova_token"]
    atteso_dict = {"dept_id": atteso} if atteso else {}
    assert PT._dept(scritto) == atteso_dict
