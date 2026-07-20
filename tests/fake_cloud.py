"""Trasporto cloud FINTO (P2-8/C2) — i test non toccano mai backend né veicolo.

Tutto ciò che `core/` manda in rete passa da due sole porte:

  * `requests.post(...)`            → login BFF, refresh token, checkPassword, realtime…
  * `urllib.request.urlopen(...)`   → l'invio comando vero e proprio (`commands.send`)

`FakeCloud` sostituisce quelle due e instrada per PATH su handler registrati. È il
"seam" che rende testabile proprio la parte dove vivevano i bug: anti-lockout del PIN,
classificazione dei codici `A00xxx`, retry sul taskId rifiutato.

Uso tipico::

    cloud.on("/tsp/v1/app/cpm/checkPassword", code="A00285")   # PIN errato
    cloud.on("/asc/vehicleControl/lockControl", code="A00079")  # comando accettato

Ogni chiamata finisce in `cloud.calls` (path + body) → si asserisce non solo l'esito
ma anche QUANTE volte si è interrogato il backend: è così che si dimostra che
l'anti-lockout non ha bruciato un tentativo di troppo.
"""
from __future__ import annotations

import json
import threading
import time
import urllib.error


class FakeResponse:
    """Minimo comune denominatore fra `requests.Response` e la risposta di urlopen."""

    def __init__(self, payload: dict | str, status: int = 200) -> None:
        self._payload = payload
        self.status_code = status
        self.status = status
        self.code = status

    # — interfaccia requests —
    def json(self):
        if isinstance(self._payload, str):
            raise ValueError("body non JSON")
        return self._payload

    @property
    def text(self) -> str:
        return self._payload if isinstance(self._payload, str) else json.dumps(self._payload)

    # — interfaccia urlopen (context manager) —
    def read(self) -> bytes:
        return self.text.encode()

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


class FakeCloud:
    """Router di risposte finte + registro delle chiamate ricevute."""

    def __init__(self) -> None:
        self._routes: dict[str, object] = {}
        self._default = {"code": "000000"}
        self.calls: list[dict] = []
        self._lock = threading.Lock()

    # ───────────────────────── configurazione delle risposte ─────────────────────────
    def on(self, path_fragment: str, response=None, *, code=None, data=None,
           status: int = 200, raises: Exception | None = None, delay: float = 0.0):
        """Registra la risposta per ogni path che CONTIENE `path_fragment`.

        `response` può essere un dict, una stringa (body non-JSON) oppure un callable
        `fn(path, body) -> dict` per gli scenari che cambiano risposta a ogni chiamata
        (es. "il primo taskId viene rifiutato, il secondo accettato").

        `delay` = latenza finta in secondi. Serve ai test di CONCORRENZA: un backend che
        risponde istantaneamente non lascia alcuna finestra fra il controllo di una
        guardia e il suo aggiornamento, quindi una corsa reale non si riprodurrebbe e il
        test passerebbe anche col bug presente (verificato: senza latenza il test della
        corsa P0-1 era cieco). Una POST vera verso Chery costa decimi di secondo: è
        proprio quella finestra che il lock deve coprire."""
        if raises is not None:
            self._routes[path_fragment] = raises
            return self
        if response is None:
            response = {}
            if code is not None:
                response["code"] = code
            if data is not None:
                response["data"] = data
        self._routes[path_fragment] = (response, status, delay)
        return self

    def default(self, response: dict):
        self._default = response
        return self

    # ───────────────────────── instradamento ─────────────────────────
    def _resolve(self, path: str, body: dict | None):
        with self._lock:
            self.calls.append({"path": path, "body": body})
        # match sul frammento più lungo: `/asc/vehicleControl/lockControl` deve
        # vincere su un eventuale `/asc/vehicleControl` generico.
        best = None
        for frag in self._routes:
            if frag in path and (best is None or len(frag) > len(best)):
                best = frag
        if best is None:
            return FakeResponse(self._default)
        entry = self._routes[best]
        if isinstance(entry, Exception):
            raise entry
        response, status, delay = entry
        if delay:
            time.sleep(delay)
        if callable(response):
            response = response(path, body)
        return FakeResponse(response, status)

    def calls_to(self, path_fragment: str) -> list[dict]:
        """Le sole chiamate il cui path contiene il frammento (per contare i tentativi)."""
        return [c for c in self.calls if path_fragment in c["path"]]

    def count(self, path_fragment: str) -> int:
        return len(self.calls_to(path_fragment))

    def reset_calls(self) -> None:
        with self._lock:
            self.calls.clear()

    # ───────────────────────── installazione (monkeypatch) ─────────────────────────
    def install(self, monkeypatch) -> "FakeCloud":
        """Sostituisce le DUE porte di rete. Si patcha il modulo `requests` a livello di
        package (non l'attributo di un singolo modulo core/) perché `commands._mint_taskid_impl`
        fa `import requests` DENTRO la funzione: patchare `commands.requests` non basterebbe."""
        import requests
        import urllib.request

        def fake_post(url, data=None, params=None, headers=None, timeout=None, **kw):
            return self._resolve(url, _decode(data))

        def fake_get(url, params=None, headers=None, timeout=None, **kw):
            return self._resolve(url, params)

        def fake_urlopen(req, timeout=None, **kw):
            url = getattr(req, "full_url", str(req))
            body = _decode(getattr(req, "data", None))
            resp = self._resolve(url, body)
            if resp.status >= 400:
                raise urllib.error.HTTPError(url, resp.status, "err", {}, None)
            return resp

        monkeypatch.setattr(requests, "post", fake_post)
        monkeypatch.setattr(requests, "get", fake_get)
        monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen)
        return self


def _decode(data):
    """Body della richiesta → dict quando possibile (i test asseriscono sui campi)."""
    if data is None:
        return None
    if isinstance(data, (bytes, bytearray)):
        data = data.decode("utf-8", "replace")
    if isinstance(data, str):
        try:
            return json.loads(data)
        except ValueError:
            return {"_raw": data}
    return data
