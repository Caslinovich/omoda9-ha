"""Test BLOCCANTE: il monitor diagnostico non deve far uscire segreti.

Il file `omoda9_<VIN>_diag.jsonl` nasce redatto ed è pensato per essere allegato a una
issue. Questi test sono la garanzia di quel claim: verificano che VIN, email, PIN, token,
taskId e GPS non compaiano MAI né nel ring buffer né nel file su disco — nemmeno dentro
campi dal nome sconosciuto, che la deny-list per chiave non coprirebbe.

`diag.py` usa solo la libreria standard proprio per essere testabile qui senza avere Home
Assistant installato: si carica dal path, senza importare il package `custom_components`.

    python3 -m pytest tests/test_diag_redaction.py -q
    python3 tests/test_diag_redaction.py          # anche senza pytest
"""
from __future__ import annotations

import importlib.util
import json
import math
import os
import sys
import tempfile
import time

_HERE = os.path.dirname(os.path.abspath(__file__))
_DIAG_PY = os.path.join(_HERE, "..", "custom_components", "omoda9", "diag.py")

_spec = importlib.util.spec_from_file_location("omoda9_diag", _DIAG_PY)
diag = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(diag)

# Valori sintetici con la STESSA FORMA di quelli reali (nessun dato vero nel repo).
# NB: scelti anche per NON far scattare `check_secrets.sh`, che cerca strutture da VIN
# reale e da tUserId reale in tutta la history — un valore di test troppo "somigliante"
# bloccherebbe il gate a ogni release. Il marcatore sul VIN è quello che lo esclude.
VIN = "LZZAAAAAA1B2C3D4E"  # VIN_PLACEHOLDER: sintetico, non è un VIN reale
EMAIL = "mario.rossi@example.com"
PIN = "4917"
TUSERID = "100000000000000001"
TOKEN = "eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxMjM0NSJ9.abcdefghijklmnop"
TASKID = "a1b2c3d4e5f60718293a4b5c6d7e8f90"
LAT, LON = 40.712776, -74.005974

# Payload realistico: chiavi note, chiavi ANNIDATE e chiavi dal nome inventato che la
# deny-list non conosce (è lì che la passata regex deve salvare la situazione).
PAYLOAD = {
    "vin": VIN,
    "email": EMAIL,
    "pin": PIN,
    "tUserId": TUSERID,
    "userToken": TOKEN,
    "taskId": TASKID,
    "lat": LAT,
    "lon": LON,
    "position": {"latitude": LAT, "longitude": LON},
    "seq": f"{VIN}-1721390000",
    "certs_src": f"/config/omoda9_{VIN}_certs",
    "nested": {"deep": {"vin": VIN, "auth": f"Bearer {TOKEN}"}},
    # campi dal nome SCONOSCIUTO: nessuna deny-list li copre
    "campo_ignoto": f"il veicolo {VIN} di {EMAIL} usa {TOKEN}",
    "misterioso": TASKID,
    "id_strano": TUSERID,
    "doorLock": "0",
}

SECRETS = (VIN, EMAIL, TOKEN, TASKID, TUSERID, str(LAT), str(LON))


def _assert_clean(blob: str, where: str) -> None:
    for secret in SECRETS:
        assert secret not in blob, f"{where}: segreto trapelato → {secret!r}"


def test_redact_removes_every_secret():
    """Nessun segreto sopravvive alla redazione, a nessun livello di annidamento."""
    out = diag.redact(PAYLOAD, extra=(VIN, EMAIL))
    _assert_clean(json.dumps(out), "redact()")


def test_gps_is_removed_not_masked():
    """La posizione non si maschera: sparisce. Non deve uscire neanche approssimata."""
    out = diag.redact(PAYLOAD, extra=(VIN, EMAIL))
    for key in ("lat", "lon", "position"):
        assert key not in out, f"chiave geo {key!r} ancora presente"
    assert "latitude" not in json.dumps(out)


def test_checkpassword_stays_readable():
    """`cp_code`/`cp_msg` restano IN CHIARO: sono ciò che distingue un PIN errato da un
    rifiuto per permessi, e non sono sensibili."""
    out = diag.redact({"cp_code": "A00285", "cp_msg": "password error"}, extra=(VIN,))
    assert out["cp_code"] == "A00285"
    assert out["cp_msg"] == "password error"


def test_pin_never_recorded():
    """Il PIN non entra nel buffer in nessuna forma, nemmeno se lo si passasse a mano."""
    rec = _recorder()
    try:
        rec.record("pin_event", outcome="fail", pin=PIN, password=PIN, cp_code="A00285")
        blob = json.dumps(rec.snapshot())
        assert PIN not in blob.replace('"n": 0', "")  # il PIN a 4 cifre, non i contatori
        assert "A00285" in blob
    finally:
        rec.close()


def test_recorder_buffer_and_file_are_redacted():
    """Il DUE uscite del monitor — ring buffer e file su disco — nascono già redatte."""
    rec = _recorder()
    try:
        rec.record("mqtt_frame", svc="5A02", payload=PAYLOAD)
        rec.record("command", key="blocca", ok=False, msg=f"errore per {VIN} ({EMAIL})")
        rec.close()  # svuota la coda e ferma lo scrittore
        _assert_clean(json.dumps(rec.snapshot()), "snapshot()")
        with open(rec.path, encoding="utf-8") as fh:
            content = fh.read()
        _assert_clean(content, "file jsonl")
        assert [json.loads(l) for l in content.splitlines() if l.strip()], "file vuoto"
    finally:
        rec.close()


def test_counters_and_unknown_fields():
    """I contatori aggregati sono la sintesi che fa vedere il problema senza leggere
    500 eventi; `unknown_field` si emette una volta sola per chiave ma conta sempre."""
    rec = _recorder()
    try:
        rec.record("command", key="a", ok=True, duration_ms=120)
        rec.record("command", key="b", ok=False, duration_ms=900)
        rec.record("pin_fail_concurrent", inflight=2)
        rec.record("hv_followup", orphan=True, closing=True)
        for _ in range(3):
            rec.note_unknown_field("rangeKm", "215", "5A02")
        snap = rec.snapshot()
        assert snap["counters"]["commands_total"] == 2
        assert snap["counters"]["commands_failed"] == 1
        assert snap["counters"]["pin_fail_concurrent"] == 1
        assert snap["counters"]["hv_followup_orphan"] == 1
        # il contatore vede TUTTE e 3 le occorrenze (è il conteggio a dire se il campo è
        # stabile e vale la pena mapparlo), ma l'evento si emette una volta sola
        assert snap["unknown_fields"]["rangeKm"] == 3
        assert len([e for e in snap["events"] if e["type"] == "unknown_field"]) == 1
        assert snap["latency"]["command"]["n"] == 2
    finally:
        rec.close()


def test_switch_expires_and_disarms():
    """La bandierina scade da sola: finestra chiusa → niente monitor, file rinominato."""
    with tempfile.TemporaryDirectory() as d:
        path = os.path.join(d, diag.SWITCH_ON)
        with open(path, "w") as fh:
            fh.write("3")
        assert diag.read_switch(path) is not None, "finestra appena aperta: deve valere"

        old = time.time() - 4 * 86400          # attivata 4 giorni fa, durata 3
        os.utime(path, (old, old))
        assert diag.read_switch(path) is None, "finestra scaduta: non deve attivarsi"
        assert not os.path.exists(path), "la bandierina scaduta va disarmata"
        assert os.path.exists(os.path.join(d, diag.SWITCH_OFF))


def test_switch_zero_never_expires():
    """Bandierina a `0` = nessuna scadenza: il monitor non deve spegnersi da solo.

    Si verifica anche col file vecchissimo, perché il baco naturale qui sarebbe che la
    finestra venga calcolata lo stesso sull'mtime e il monitor risulti già scaduto."""
    for content in ("0", "sempre", "ALWAYS"):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, diag.SWITCH_ON)
            with open(path, "w") as fh:
                fh.write(content)
            old = time.time() - 400 * 86400
            os.utime(path, (old, old))
            assert diag.read_switch(path) == math.inf, f"«{content}» non deve scadere"
            assert os.path.exists(path), "la bandierina senza scadenza non va disarmata"
            assert not os.path.exists(os.path.join(d, diag.SWITCH_OFF))
    # e la data non-data non deve far esplodere né il .jsonl né la diagnostica HA
    assert diag._iso(math.inf) == "senza scadenza"


def test_absent_switch_is_dormant():
    """Nessuna bandierina = monitor dormiente. È il caso normale in produzione."""
    with tempfile.TemporaryDirectory() as d:
        assert diag.read_switch(os.path.join(d, diag.SWITCH_ON)) is None


def _recorder() -> "diag.DiagRecorder":
    tmp = tempfile.mkdtemp()
    return diag.DiagRecorder(os.path.join(tmp, "omoda9_TEST_diag.jsonl"),
                             vin=VIN, email=EMAIL, until=time.time() + 3600)


if __name__ == "__main__":
    failed = 0
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            try:
                fn()
                print(f"  ok  {name}")
            except AssertionError as err:
                failed += 1
                print(f"FAIL  {name}: {err}")
    print("-" * 50)
    print("TUTTI I TEST PASSATI" if not failed else f"{failed} TEST FALLITI")
    sys.exit(1 if failed else 0)
