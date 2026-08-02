"""`core/tls_client.py` — la scala di client che supera il filtro anti-bot di `sendSmsCode`.

Qui NON si verifica che il server accetti: quello si può misurare solo dal vivo (ed è stato
fatto il 2026-08-02, in finestre separate, perché l'endpoint blocca l'IP dopo tre richieste
ravvicinate). Si verifica il comportamento della scala, che è ciò che si rompe in silenzio:

  * si scende finché uno passa, e non oltre;
  * il **blocco sull'IP** (HTTP 405) ferma tutto subito, perché contro quello cambiare client
    non serve a nulla e ogni tentativo in più allunga il blocco. Questa è la distinzione che
    prima non esisteva: qualunque risposta non-JSON veniva chiamata «probabile blocco WAF»,
    mettendo nello stesso cesto due guasti che chiedono rimedi opposti — «cambia client»
    contro «aspetta e non insistere»;
  * un client assente o rotto viene saltato, non fa fallire il giro;
  * il client che ha funzionato viene ricordato, così il login dopo costa UNA richiesta sola.
"""
from __future__ import annotations

import pytest

from custom_components.omoda9.core import tls_client as T


PAGINA_WAF = '<!doctypehtml><meta charset="UTF-8"><meta name="aliyun_waf_aa" content="…">'
PAGINA_BAN = '<!doctypehtml><html lang="zh-cn">…'
RISPOSTA_OK = '{"key":"operation.successful","ok":true}'


@pytest.fixture(autouse=True)
def _memoria_isolata(tmp_path, monkeypatch):
    """La memoria del client vincente vive accanto al token: qui la si sposta in una cartella
    temporanea, così i test non si scrivono addosso né toccano una configurazione vera."""
    monkeypatch.setenv("OMODA_TOKEN_PATH", str(tmp_path / "token.json"))
    monkeypatch.delenv("OMODA_TLS_CLIENT", raising=False)


def _scala(monkeypatch, **risposte):
    """Sostituisce i client veri con funzioni finte, registrando chi viene chiamato."""
    chiamati: list[str] = []

    def finto(nome, esito):
        def _f(url, data, headers, timeout):
            chiamati.append(nome)
            if isinstance(esito, Exception):
                raise esito
            return esito
        return _f

    monkeypatch.setattr(T, "CLIENT", {n: finto(n, e) for n, e in risposte.items()})
    monkeypatch.setattr(T, "SCALA", list(risposte))
    return chiamati


def _post(timeout=30):
    """`timeout` è il budget COMPLESSIVO della scala, non di ogni gradino: qui si passa un
    valore realistico perché i client finti rispondono all'istante e il tempo non è il
    soggetto della prova."""
    return T.post_waf("https://esempio.invalid/x", {"a": "b"}, {"H": "v"}, timeout=timeout)


def test_si_ferma_al_primo_che_passa(monkeypatch):
    chiamati = _scala(monkeypatch,
                      primo=(200, RISPOSTA_OK),
                      secondo=(200, RISPOSTA_OK))
    esito = _post()
    assert esito.passato and esito.client == "primo"
    assert chiamati == ["primo"], "non deve provare i client successivi"


def test_scende_la_scala_quando_il_filtro_respinge(monkeypatch):
    chiamati = _scala(monkeypatch,
                      primo=(200, PAGINA_WAF),
                      secondo=(200, PAGINA_WAF),
                      terzo=(200, RISPOSTA_OK))
    esito = _post()
    assert esito.passato and esito.client == "terzo"
    assert chiamati == ["primo", "secondo", "terzo"]


def test_il_blocco_sull_ip_ferma_subito_la_scala(monkeypatch):
    """Il difetto che questo presidia: insistere su un ban IP peggiora il ban.

    Misurato dal vivo — dopo tre richieste ravvicinate l'endpoint ha risposto 405 a TUTTI i
    client per oltre mezz'ora. Se la scala continuasse, un solo tentativo di login ne
    sparerebbe quattro."""
    chiamati = _scala(monkeypatch,
                      primo=(405, PAGINA_BAN),
                      secondo=(200, RISPOSTA_OK))
    esito = _post()
    assert not esito.passato
    assert esito.bloccato_ip, "il 405 va riconosciuto come blocco temporaneo sull'IP"
    assert chiamati == ["primo"], "dopo un ban sull'IP non si prova nessun altro client"


def test_il_405_con_risposta_json_non_e_un_ban(monkeypatch):
    """Un 405 applicativo, col suo corpo JSON, è una risposta del server: il WAF è stato
    superato e la scala ha finito il suo lavoro."""
    _scala(monkeypatch, primo=(405, RISPOSTA_OK))
    esito = _post()
    assert esito.passato and not esito.bloccato_ip


def test_un_client_assente_viene_saltato(monkeypatch):
    chiamati = _scala(monkeypatch,
                      assente=ImportError("no module"),
                      senza_eseguibile=FileNotFoundError("curl"),
                      rotto=RuntimeError("boom"),
                      buono=(200, RISPOSTA_OK))
    esito = _post()
    assert esito.passato and esito.client == "buono"
    assert chiamati == ["assente", "senza_eseguibile", "rotto", "buono"]


def test_nessun_client_disponibile_non_solleva(monkeypatch):
    """`post_waf` non deve mai propagare: il chiamante è un sottoprocesso il cui unico modo di
    parlare è lo stdout, e un traceback lì diventa il «motivo» mostrato all'utente."""
    _scala(monkeypatch, unico=ImportError("no"))
    esito = _post()
    assert not esito.passato and not esito.bloccato_ip


def test_ricorda_il_client_che_ha_funzionato(monkeypatch):
    _scala(monkeypatch, primo=(200, PAGINA_WAF), secondo=(200, RISPOSTA_OK))
    assert _post().client == "secondo"

    # secondo giro: il vincente va provato per PRIMO, così si spende una richiesta sola
    chiamati = _scala(monkeypatch, primo=(200, PAGINA_WAF), secondo=(200, RISPOSTA_OK))
    assert _post().client == "secondo"
    assert chiamati == ["secondo"]


def test_la_memoria_non_e_mai_bloccante(monkeypatch):
    """Se il file non è scrivibile (permessi, disco pieno) il login deve funzionare lo stesso:
    ricordare il vincente è un'ottimizzazione, non un requisito."""
    monkeypatch.setenv("OMODA_TOKEN_PATH", "/percorso/che/non/esiste/token.json")
    _scala(monkeypatch, unico=(200, RISPOSTA_OK))
    assert _post().passato


def test_si_puo_forzare_un_client_solo(monkeypatch):
    """`OMODA_TLS_CLIENT` serve a isolare un client in diagnostica senza consumare tentativi
    con gli altri — e i tentativi, su questo endpoint, sono contati."""
    monkeypatch.setenv("OMODA_TLS_CLIENT", "secondo")
    chiamati = _scala(monkeypatch, primo=(200, RISPOSTA_OK), secondo=(200, PAGINA_WAF))
    esito = _post()
    assert chiamati == ["secondo"] and not esito.passato


def test_un_nome_forzato_inesistente_non_blocca_tutto(monkeypatch):
    monkeypatch.setenv("OMODA_TLS_CLIENT", "inventato")
    chiamati = _scala(monkeypatch, primo=(200, RISPOSTA_OK))
    assert _post().passato and chiamati == ["primo"]


def _server_locale():
    """Server HTTP di prova, in ascolto solo su 127.0.0.1: nessuna richiesta esce di qui."""
    import http.server
    import threading

    ricevuto: dict = {}

    class H(http.server.BaseHTTPRequestHandler):
        def do_POST(self):
            n = int(self.headers.get("Content-Length") or 0)
            ricevuto["corpo"] = self.rfile.read(n).decode()
            ricevuto["headers"] = {k.lower(): v for k, v in self.headers.items()}
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(b'{"ok":true}')

        def log_message(self, *a):
            pass

    srv = http.server.HTTPServer(("127.0.0.1", 0), H)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv, ricevuto


@pytest.mark.skipif(not __import__("shutil").which("curl"), reason="curl non installato")
def test_il_ramo_curl_non_e_iniettabile(tmp_path, socket_enabled):
    """Regressione su un difetto vero, introdotto e corretto il 2026-08-02.

    Il file di configurazione di `curl` è **una opzione per riga**: un valore che contenga un
    ritorno a capo chiude la riga, e ciò che segue viene letto come un'OPZIONE NUOVA. Con
    `output`/`upload-file`/`proxy` si scrive, si legge o si spedisce fuori un file qualsiasi —
    per esempio il token dell'auto. Le intestazioni includono `channelId`/`countryId`/
    `tenantCode`, che arrivano da campi di testo liberi del config flow: la strada c'è.
    Schermare le sole virgolette non bastava."""
    # `socket_enabled` toglie il divieto globale sui socket: qui serve un server in
    # ascolto su 127.0.0.1, e nessuna richiesta esce dalla macchina.
    srv, ricevuto = _server_locale()
    bersaglio = tmp_path / "iniezione_riuscita.txt"
    # DUE payload distinti, perché i bersagli sono due e il primo test ne copriva uno solo.
    #   * opzioni del file di configurazione (`output = …`), risolto schermando `\n`;
    #   * ⚠️ INTESTAZIONI HTTP. Qui schermare non basta: `curl` riespande la sequenza dentro
    #     il valore e la scrive sul filo. La prima versione di questo test usava
    #     `user-agent = "X"` come payload — che NON è sintassi HTTP (manca il due punti),
    #     quindi passava per come era scritto il payload, non perché ci fosse una difesa.
    ostile_conf = f'X\nuser-agent = "INIETTATO"\noutput = "{bersaglio}"'
    ostile_http = "X\nUser-Agent: INIETTATO\nX-Falso: 1"

    stato, _testo = T._post_curl(f"http://127.0.0.1:{srv.server_port}/x",
                                 {"cap": ostile_conf},
                                 {"channelId": ostile_http, "countryId": ostile_conf}, 15)
    srv.shutdown()

    assert stato == 200
    assert not bersaglio.exists(), "curl ha eseguito l'opzione `output` iniettata nel valore"
    assert "INIETTATO" not in ricevuto["headers"].get("user-agent", "")
    assert "x-falso" not in ricevuto["headers"], "intestazione HTTP iniettata dal valore"


@pytest.mark.skipif(not __import__("shutil").which("curl"), reason="curl non installato")
def test_il_ramo_curl_non_deforma_i_valori(socket_enabled):
    """L'altra metà: schermare non deve neanche alterare. Se un token del captcha arrivasse
    storto, il login fallirebbe con un errore che accusa il codice."""
    import urllib.parse

    srv, ricevuto = _server_locale()
    valori = {"normale": "3001234567",           # PHONE_PLACEHOLDER
              "base64": "abc+/=DEF123",          # forma tipica del token del captcha
              "virgolette": 'a"b', "backslash": "a\\b",
              "aCapo": "a\nb", "tab": "a\tb", "accenti": "città però"}
    T._post_curl(f"http://127.0.0.1:{srv.server_port}/x", valori, {"H": "v"}, 15)
    srv.shutdown()

    campi = dict(urllib.parse.parse_qsl(ricevuto["corpo"], keep_blank_values=True))
    assert campi == valori


def test_json_illeggibile_non_solleva():
    assert T.Esito(200, "{non json", "x").json() == {}


def test_il_corpo_del_waf_non_viene_scambiato_per_json():
    assert not T.Esito(200, PAGINA_WAF, "x").passato
    assert not T.Esito(200, "", "x").passato
    assert T.Esito(200, "  " + RISPOSTA_OK, "x").passato, "spazi in testa non devono ingannare"
