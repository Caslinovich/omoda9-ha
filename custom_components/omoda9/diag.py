"""Monitor diagnostico — strumento per lo SVILUPPATORE del componente, non per l'utente.

Registra su file gli eventi runtime che servono a scovare i bug di campo (conii PIN
concorrenti, campi telemetria non mappati, esiti/latenza dei comandi, riconnessioni
MQTT, timer HV orfani, salute sessione). NON è una funzione dell'integrazione: non ha
interruttore nell'interfaccia, non compare nel changelog e non si annuncia all'utente.

ATTIVAZIONE — file «bandierina» nella config dir di Home Assistant:

    /config/omoda9_diag.on        contenuto = numero di GIORNI (default 3, max 7)
                                  oppure `0` = NESSUNA scadenza (spegnimento manuale)

Presente  → il monitor parte al caricamento dell'integrazione e si spegne DA SOLO alla
            scadenza (contata dalla data di modifica del file), che viene rinominato in
            `omoda9_diag.off`. Nessun intervento manuale necessario.
            Con `0` invece resta acceso a tempo indeterminato e si spegne SOLO
            cancellando la bandierina: da usare quando l'evento da osservare è raro e
            una finestra fissa rischierebbe di chiudersi proprio prima che capiti.
            Il file resta comunque limitato dalla rotazione (2 MB + un `.1`).
Assente   → il codice è completamente DORMIENTE: `coordinator._diag` e
            `commands.DIAG_HOOK` restano `None`, quindi ogni punto di aggancio è un
            singolo confronto `is not None` e non si alloca nulla. Costo nullo sul
            percorso caldo (il callback MQTT gira per ogni push dell'auto).

REDAZIONE ALLA SORGENTE — il principio che rende il file condivisibile. I dati sensibili
si mascherano quando l'evento ENTRA nel buffer, non all'esportazione: il `.jsonl` su
disco NASCE già oscurato, perciò anche se finisse allegato a una issue per sbaglio non
conterrebbe segreti. La geolocalizzazione non viene mascherata ma RIMOSSA (dove abiti non
deve uscire nemmeno approssimato). Restano volutamente IN CHIARO solo `cp_code`/`cp_msg`,
cioè codice e messaggio grezzi di `checkPassword`: non sono sensibili e sono l'unico modo
per distinguere un PIN davvero errato da un rifiuto per permessi/parametri.

Thread-safety: gli eventi arrivano da thread diversi (il thread paho per l'MQTT, gli
executor per i comandi, il loop di HA per la sessione) → deque e contatori vivono sotto un
lock dedicato. La scrittura su disco è delegata a un thread scrittore con coda, così
nessun I/O blocca mai il thread paho o l'event loop.
"""
from __future__ import annotations

import json
import math
import os
import queue
import re
import threading
import time
from collections import Counter, deque
from typing import Any

# ───────────────────────── parametri ─────────────────────────

SWITCH_ON = "omoda9_diag.on"     # bandierina di attivazione (config dir di HA)
SWITCH_OFF = "omoda9_diag.off"   # nome dopo l'auto-spegnimento

DEFAULT_DAYS = 3
MAX_DAYS = 7
# Contenuti della bandierina che disattivano l'auto-spegnimento (confronto minuscolo).
_NO_EXPIRY = frozenset({"0", "sempre", "always", "inf"})
BUFFER_MAX = 500                 # eventi tenuti in RAM (ring buffer per la diagnostica HA)
FILE_MAX_BYTES = 2 * 1024 * 1024  # rotazione del .jsonl (si tiene anche un .jsonl.1)
QUEUE_MAX = 2000                 # righe in attesa di scrittura; oltre, si scarta e si conta
MAX_DEPTH = 6                    # profondità massima esplorata nella redazione ricorsiva
MAX_ITEMS = 60                   # elementi massimi per dict/lista (payload patologici)
MAX_STR = 400                    # lunghezza massima di una stringa registrata

# ───────────────────────── redazione ─────────────────────────

# Chiavi il cui VALORE va sostituito integralmente (confronto case-insensitive, a ogni
# livello di annidamento). Identità account, identità veicolo, materiale crittografico.
REDACT_KEYS = {
    "email", "pin", "password", "passwd", "token", "usertoken", "access_token",
    "refresh_token", "accesstoken", "refreshtoken", "authorization", "sign",
    "taskid", "tuserid", "tuid", "secret", "certs_src",
    # NB: solo chiavi crittografiche SPECIFICHE. Un generico "key" qui oscurerebbe il
    # NOME del comando e delle chiavi 5A02 non mappate (`key` è il loro campo) — cioè
    # proprio ciò che i due hook servono a mostrare. I segreti in campi dal nome diverso
    # restano coperti dalla passata regex su esadecimale lungo/JWT/PEM.
    "privatekey", "secretkey", "apikey", "appkey", "keyfile", "clientkey",
    "vin", "carvin", "seq", "nickname", "fullname", "plate", "targa",
}

# Chiavi RIMOSSE del tutto, non mascherate: la posizione non deve uscire in nessuna forma.
DROP_KEYS = {
    "lat", "lon", "latitude", "longitude", "position", "gpslat", "gpslon",
    "gpstime", "positiontime", "altitude", "heading", "direction",
}

# Chiavi lasciate IN CHIARO: codice/messaggio grezzi di checkPassword, non sensibili e
# indispensabili per capire se un fallimento è davvero un PIN errato (vedi docstring).
CLEAR_KEYS = {"cp_code", "cp_msg"}

REDACTED = "**REDACTED**"

# Rete di sicurezza sulle STRINGHE: intercetta un segreto anche dentro un campo dal nome
# sconosciuto, che la deny-list per chiave non coprirebbe. L'ordine conta: i pattern più
# specifici (JWT, PEM) precedono quelli generici (esadecimale lungo).
_PATTERNS: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r"-----BEGIN[^-]{0,50}-----.*?-----END[^-]{0,50}-----", re.S), "**PEM**"),
    (re.compile(r"-----BEGIN[^-]{0,50}-----"), "**PEM**"),
    (re.compile(r"eyJ[A-Za-z0-9_-]{10,}(?:\.[A-Za-z0-9_-]+){0,2}"), "**JWT**"),
    (re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}"), "**EMAIL**"),
    (re.compile(r"\b[A-HJ-NPR-Z0-9]{17}\b"), "**VIN**"),
    (re.compile(r"\b\d{15,}\b"), "**NUM**"),          # tUserId & affini (id numerici lunghi)
    (re.compile(r"\b[0-9a-fA-F]{32,}\b"), "**HEX**"),  # token/hash/SM4
    (re.compile(r"/config/omoda9_\S*"), "**PATH**"),   # path per-VIN nella config dir
    # COORDINATA GEOGRAFICA in un campo dal nome qualsiasi. `DROP_KEYS` toglie la
    # posizione quando la si riconosce dal NOME della chiave; questo pattern la prende
    # anche quando il nome non dice nulla — è il caso che ha causato la fuga vista in
    # campo il 2026-07-20, dove una coordinata era finita sotto la chiave `sample`.
    # Volutamente stretto: parte intera di 1-3 cifre e ALMENO 4 decimali. Non tocca i
    # valori di telemetria reali (temperature "21.0", tensioni "384", percentuali "72")
    # né i timestamp epoch, che hanno la parte intera ben più lunga di 3 cifre.
    (re.compile(r"-?\b\d{1,3}\.\d{4,}\b"), "**GEO**"),
]


def _redact_str(s: str, extra: tuple[str, ...] = ()) -> str:
    """Oscura una stringa: prima i valori noti dell'entry (VIN, email), poi i pattern."""
    if not s:
        return s
    for val in extra:
        if val and len(val) >= 4 and val in s:
            s = s.replace(val, REDACTED)
    for pat, repl in _PATTERNS:
        s = pat.sub(repl, s)
    return s[:MAX_STR]


def redact(obj: Any, extra: tuple[str, ...] = (), _depth: int = 0) -> Any:
    """Redazione ricorsiva di un oggetto arbitrario, applicata ALLA CATTURA.

    Tre regole, nell'ordine: le chiavi geo spariscono, le chiavi sensibili diventano
    `**REDACTED**`, tutto il resto scende ricorsivamente e ogni stringa passa comunque
    dai pattern. Le chiavi di `CLEAR_KEYS` sono l'unica eccezione voluta."""
    if _depth > MAX_DEPTH:
        return "**DEPTH**"
    if isinstance(obj, dict):
        out: dict[str, Any] = {}
        for i, (k, v) in enumerate(obj.items()):
            if i >= MAX_ITEMS:
                out["**TRUNCATED**"] = len(obj) - MAX_ITEMS
                break
            ks = str(k)
            kl = ks.lower()
            if kl in DROP_KEYS:
                continue          # geolocalizzazione: rimossa, non mascherata
            if kl in CLEAR_KEYS:
                out[ks] = v if v is None else str(v)[:MAX_STR]
                continue
            if kl in REDACT_KEYS:
                out[ks] = REDACTED if v is not None else None
                continue
            out[ks] = redact(v, extra, _depth + 1)
        return out
    if isinstance(obj, (list, tuple)):
        return [redact(v, extra, _depth + 1) for v in list(obj)[:MAX_ITEMS]]
    if isinstance(obj, str):
        return _redact_str(obj, extra)
    if isinstance(obj, (int, float, bool)) or obj is None:
        return obj
    return _redact_str(str(obj), extra)


# ───────────────────── bandierina di attivazione ─────────────────────

def read_switch(path: str) -> float | None:
    """Legge la bandierina. Ritorna l'istante di scadenza (epoch) o None se il monitor
    non va attivato. Se la finestra è già scaduta, spegne rinominando il file in `.off`.

    Contenuto `0` (o `sempre`/`always`) → **nessuna scadenza**: ritorna `math.inf` e il
    monitor resta acceso finché non lo si spegne a mano cancellando la bandierina. Serve
    quando non si sa quanto durerà l'osservazione — un evento raro (comandi sovrapposti,
    reload durante la ricarica) può non capitare entro una finestra fissa, e trovare il
    monitor spento da solo significa aver perso i giorni di attesa. Il file su disco resta
    comunque limitato dalla rotazione (2 MB + un `.1`), quindi «acceso per sempre» non è
    un rischio di spazio; il costo è solo il logger verboso.

    La durata parte dalla data di MODIFICA del file: `touch` sulla bandierina rinnova la
    finestra senza doverne cambiare il contenuto. Sola lettura + un eventuale rename:
    da chiamare in executor, mai sul loop."""
    try:
        st = os.stat(path)
    except OSError:
        return None
    try:
        with open(path) as fh:
            raw = fh.read(32).strip()
    except OSError:
        raw = ""
    if raw.lower() in _NO_EXPIRY:
        return math.inf
    try:
        days = int(raw) if raw else DEFAULT_DAYS
    except ValueError:
        days = DEFAULT_DAYS
    days = max(1, min(MAX_DAYS, days))
    until = st.st_mtime + days * 86400
    if time.time() >= until:
        disarm_switch(path)
        return None
    return until


def disarm_switch(path: str) -> None:
    """Spegne la bandierina rinominandola (`.on` → `.off`): il monitor non riparte al
    prossimo avvio, ma resta traccia di quando è stato attivo. Non solleva mai."""
    try:
        os.replace(path, os.path.join(os.path.dirname(path), SWITCH_OFF))
    except OSError:
        pass


# ───────────────────────── registratore ─────────────────────────

class DiagRecorder:
    """Ring buffer + contatori + file JSONL rotante, tutto già redatto alla sorgente."""

    def __init__(self, jsonl_path: str, vin: str = "", email: str = "",
                 until: float | None = None) -> None:
        self.path = jsonl_path
        self.until = until
        self._extra = tuple(v for v in (vin, email) if v)
        self._lock = threading.Lock()
        self._events: deque[dict] = deque(maxlen=BUFFER_MAX)
        self._counters: Counter[str] = Counter()
        self._cp_codes: Counter[str] = Counter()
        self._unknown: Counter[str] = Counter()
        self._seen_unknown: set[str] = set()
        self._latency: dict[str, list[int]] = {}
        self._dropped = 0
        self._q: queue.Queue = queue.Queue(maxsize=QUEUE_MAX)
        self._closed = False
        self._writer = threading.Thread(target=self._writer_loop, name="omoda9_diag",
                                        daemon=True)
        self._writer.start()
        self.record("diag_start", until=_iso(until) if until else None)

    # ---------- cattura ----------

    def record(self, etype: str, **fields: Any) -> None:
        """Registra un evento. È il `DIAG_HOOK` passato ai moduli core/.

        Non solleva MAI: un monitor difettoso non deve poter rompere l'integrazione che
        sta osservando (in particolare non deve far fallire un comando all'auto)."""
        try:
            ev = {"ts": _iso(time.time()), "type": etype}
            ev.update(redact(fields, self._extra))
            with self._lock:
                if self._closed:
                    return
                self._events.append(ev)
                self._counters[etype] += 1
                self._tally(etype, ev)
            try:
                self._q.put_nowait(json.dumps(ev, default=str, ensure_ascii=False))
            except queue.Full:
                with self._lock:
                    self._dropped += 1
        except Exception:  # noqa: BLE001 — vedi docstring: il monitor non fa danni
            pass

    def _tally(self, etype: str, ev: dict) -> None:
        """Contatori aggregati — la SINTESI che fa vedere un problema senza leggere 500
        eventi. Chiamato già sotto `self._lock`."""
        if etype == "command":
            self._counters["commands_total"] += 1
            if not ev.get("ok"):
                self._counters["commands_failed"] += 1
            ms = ev.get("duration_ms")
            if isinstance(ms, int):
                self._latency.setdefault("command", []).append(ms)
        elif etype == "pin_event":
            outcome = ev.get("outcome")
            self._counters[f"pin_{outcome}"] += 1
            code = ev.get("cp_code")
            if code:
                self._cp_codes[str(code)] += 1
        # NB: `pin_fail_concurrent` non ha un ramo qui — il contatore per tipo di evento
        # (già incrementato dal chiamante) porta di suo quel nome. Contarlo di nuovo lo
        # raddoppierebbe, facendo sembrare la corsa il doppio più frequente di com'è.
        elif etype == "mqtt_conn":
            self._counters[f"mqtt_{ev.get('event')}"] += 1
            up = ev.get("uptime_s")
            if isinstance(up, (int, float)):
                cur_min = self._counters.get("_mqtt_up_min")
                self._counters["_mqtt_up_min"] = up if cur_min is None else min(cur_min, up)
                self._counters["_mqtt_up_max"] = max(self._counters.get("_mqtt_up_max", 0), up)
        elif etype == "unknown_field":
            key = ev.get("key")
            if key:
                self._unknown[str(key)] += 1
        elif etype == "hv_followup":
            self._counters["hv_followup_orphan" if ev.get("orphan")
                           else "hv_followup_arms"] += 1
        elif etype == "session":
            self._counters["session_ok" if ev.get("ok") else "session_fail"] += 1
            if ev.get("triggered_reauth"):
                self._counters["reauth_triggered"] += 1

    def note_unknown_field(self, key: str, value: Any, svc: str) -> None:
        """Auto-discovery dei campi 5A02 non ancora mappati in META.

        Emette l'evento SOLO la prima volta che vede una chiave (altrimenti ogni push
        dell'auto ne genererebbe uno) ma incrementa il contatore sempre: è il conteggio a
        dire se il campo è stabile e vale la pena mapparlo.

        ⚠️ Il `sample` è il punto più delicato del monitor: è l'unico posto in cui un
        valore dell'auto viene registrato **sotto un nome di chiave che non è il suo**
        (`sample`). La redazione per chiave non può quindi proteggerlo — e infatti il
        2026-07-20 una coordinata GPS è finita in chiaro nel file proprio da qui. Il
        valore passa ora da `redact()` come tutto il resto (che dalla stessa data
        riconosce anche le coordinate), e per le chiavi geografiche il campione non
        viene proprio registrato: per capire se un campo vale un sensore basta il NOME."""
        with self._lock:
            first = key not in self._seen_unknown
            self._seen_unknown.add(key)
            if not first:
                self._unknown[key] += 1
                return
        if str(key).lower() in DROP_KEYS:
            # posizione: il nome della chiave basta, il valore non serve a nulla
            self.record("unknown_field", key=key, sample="**GEO**", svc=svc)
            return
        self.record("unknown_field", key=key, sample=str(value)[:80], svc=svc)

    # ---------- lettura ----------

    def snapshot(self) -> dict[str, Any]:
        """Ring buffer + contatori, per la diagnostica scaricabile di HA. Già redatto."""
        with self._lock:
            lat = {op: _percentiles(v) for op, v in self._latency.items()}
            counters = {k: v for k, v in self._counters.items() if not k.startswith("_")}
            counters["mqtt_uptime_min_s"] = self._counters.get("_mqtt_up_min")
            counters["mqtt_uptime_max_s"] = self._counters.get("_mqtt_up_max")
            return {
                "until": _iso(self.until) if self.until else None,
                "buffer_size": len(self._events),
                "dropped_lines": self._dropped,
                "counters": counters,
                "checkPassword_codes": dict(self._cp_codes),
                "unknown_fields": dict(self._unknown),
                "latency": lat,
                "events": list(self._events),
            }

    # ---------- scrittura su disco ----------

    def _writer_loop(self) -> None:
        """Thread dedicato: nessun I/O sul thread paho né sull'event loop di HA."""
        while True:
            line = self._q.get()
            if line is None:
                return
            try:
                self._rotate_if_needed()
                with open(self.path, "a", encoding="utf-8") as fh:
                    fh.write(line + "\n")
            except OSError:
                pass

    def _rotate_if_needed(self) -> None:
        try:
            if os.path.getsize(self.path) < FILE_MAX_BYTES:
                return
        except OSError:
            return
        try:
            os.replace(self.path, self.path + ".1")
        except OSError:
            pass

    def close(self) -> None:
        """Chiude il monitor: svuota la coda e ferma il thread scrittore."""
        with self._lock:
            if self._closed:
                return
            self._closed = True
        try:
            self._q.put_nowait(None)
        except queue.Full:
            pass
        self._writer.join(timeout=5)


# ───────────────────────── utilità ─────────────────────────

def _iso(ts: float | None) -> str | None:
    if not ts:
        return None
    # `math.inf` = monitor senza scadenza (bandierina a `0`): non è una data e
    # `time.localtime` solleverebbe. Si etichetta, così il .jsonl e la diagnostica HA
    # dicono a colpo d'occhio che resta acceso finché non lo si spegne a mano.
    if ts == math.inf:
        return "senza scadenza"
    return time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime(ts))


def _percentiles(vals: list[int]) -> dict[str, int]:
    if not vals:
        return {}
    s = sorted(vals)
    return {"n": len(s), "p50": s[len(s) // 2], "p95": s[min(len(s) - 1, int(len(s) * 0.95))],
            "max": s[-1]}
