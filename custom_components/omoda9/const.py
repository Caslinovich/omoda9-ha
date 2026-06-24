"""Costanti del custom component Omoda 9 / Jaecoo."""

DOMAIN = "omoda9"
PLATFORMS = ["sensor", "binary_sensor", "button", "lock", "switch", "climate",
             "number", "time", "cover", "device_tracker", "text"]

# Campi auto (5A02) ora rappresentati da entità native ATTUABILI (lock/switch/cover):
# esclusi dalla creazione di sensor/binary_sensor "di sola lettura" per non duplicarli.
# I campi comfort (sbrinamenti/volante/sedili guida-passeggero-posteriori) sono ora
# interruttori ON/OFF (vedi switch.py). NB: il sedile posteriore CENTRALE
# (mSeatHeatingState2/mSeatVentilateState2) NON ha un comando dedicato → resta sola lettura.
FIELDS_AS_RICH_ENTITY = {
    "doorLock", "frontHVACState", "trunkDoor", "sunroofState",
    "frontWindshieldHeat", "rWinHeatingState", "steerWheelHeating",
    "dSeatHeatingState", "dSeatVentilateState",
    # sedile passeggero
    "pSeatHeatingState", "pSeatVentilateState",
    # sedili posteriori SX/DX (telemetria *State2 ↔ comando bl/br SeatControl)
    "lSeatHeatingState2", "lSeatVentilateState2",
    "rSeatHeatingState2", "rSeatVentilateState2",
}

# Comandi del catalogo ora gestiti da lock/switch/cover → esclusi dai pulsanti singoli
# (il tap sul lock/switch/cover invoca lo stesso comando del catalogo).
COMMANDS_AS_RICH_ENTITY = {
    "blocca", "sblocca",
    # clima_on/clima_off ora pilotati dalla climate entity (climate.py) → niente pulsanti.
    "clima_on", "clima_off",
    # ricarica EV: switch dedicati (switch.py) → niente pulsanti singoli.
    # NB: `avvio_remoto` NON è qui → resta un pulsante (button.omoda9_avvio_remoto).
    "ricarica_start", "ricarica_stop", "ricarica_prog_on", "ricarica_prog_off",
    "baule_apri", "baule_chiudi",
    "finestrini_apri", "finestrini_chiudi",
    "tetto_apri", "tetto_chiudi",
    # comfort: ogni funzione è uno switch (ON+OFF) → niente pulsanti singoli
    "defrost_parabrezza", "defrost_parabrezza_off",
    "defrost_lunotto", "defrost_lunotto_off",
    "volante_caldo", "volante_caldo_off",
    "sedile_guida_caldo", "sedile_guida_caldo_off",
    "sedile_guida_aria", "sedile_guida_aria_off",
    "sedile_passeggero_caldo", "sedile_passeggero_caldo_off",
    "sedile_passeggero_aria", "sedile_passeggero_aria_off",
    "sedile_post_sx_caldo", "sedile_post_sx_caldo_off",
    "sedile_post_sx_aria", "sedile_post_sx_aria_off",
    "sedile_post_dx_caldo", "sedile_post_dx_caldo_off",
    "sedile_post_dx_aria", "sedile_post_dx_aria_off",
}

# Chiavi del config_entry (dati per-account, inseriti nel config flow)
CONF_EMAIL = "email"
CONF_PIN = "pin"
CONF_VIN = "vin"
CONF_TUSERID = "tuserid"

# Identità veicolo per il device HA (nome dinamico: "Omoda 9", "Jaecoo 7"…). `vehicle_name`
# = nickname/modello dall'app, salvato in entry.data (catturato al config flow o backfillato);
# è anche un'OPZIONE per l'override manuale. model/brand restano solo in entry.data.
CONF_VEHICLE_NAME = "vehicle_name"
DATA_VEHICLE_MODEL = "vehicle_model"
DATA_VEHICLE_BRAND = "vehicle_brand"
# fallback quando il modello non è (ancora) noto
DEFAULT_VEHICLE_NAME = "Omoda 9 / Jaecoo"

# Parametri di REGIONE (default = Europa). Esposti come options per supportare altre regioni.
CONF_BFF = "bff"
CONF_TSP_HOST = "tsp_host"
CONF_CAR_MQTT_HOST = "car_mqtt_host"
CONF_CAR_MQTT_PORT = "car_mqtt_port"
CONF_CHANNEL_ID = "channel_id"

# Provisioning certificati mutual-TLS MQTT (FASE 3c). Cartella (dentro il filesystem di HA)
# da cui importare i 4 cert nella certs_dir per-entry. Vuoto = i cert si mettono a mano.
CONF_CERTS_SRC = "certs_src"

# I 4 file mutual-TLS attesi nella certs_dir per-entry (= quelli del bridge certs_eu/).
CERT_FILES = ("ca.pem", "client.pem", "client.key", "eu_prd_cheryinternational.cer")

DEFAULTS = {
    CONF_BFF: "https://legend-oj.omodaauto.nl/api",
    CONF_TSP_HOST: "https://tspconsole-eu.cheryinternational.com",
    CONF_CAR_MQTT_HOST: "tspemqx-app-eu.cheryinternational.com",
    CONF_CAR_MQTT_PORT: 8083,
    CONF_CHANNEL_ID: "1",
}

# Costante app condivisa (non un segreto utente): seed per derivare la password MQTT
CAR_SEED = "fa89db3abe8045919d70c6ed3cc65bc5"

# Intervalli (secondi)
DEFAULT_SESSION_EVERY = 900
DEFAULT_AWAKE_WINDOW = 300

# Poll telemetria periodico (sveglia + lettura realtime). DUE intervalli in MINUTI,
# personalizzabili dalle opzioni dell'integrazione; 0 = disattivato:
#   - CONF_POLL_NORMAL  : a riposo/parcheggiata (default 60 min)
#   - CONF_POLL_CHARGING: quando è attaccata alla colonnina (default 30 min). Da v1.5.14 NON è
#     più il meccanismo che segue la ricarica (lo fa il loop a 2 min di CHARGING_POLL_EVERY, in
#     sola lettura): qui resta solo come BACKSTOP che avvia quel loop se l'auto non annuncia da
#     sola l'attacco del cavo, + refresh GPS periodico. Mentre carica l'auto è alimentata.
# Lo stato "attaccata" si rileva da `chargeGunState` (spina collegata).
# ⚠️ ogni ciclo SVEGLIA l'auto (vehicleLocation) per posizione + telemetria fresche anche
# a vettura parcheggiata → micro-consumo 12V e possibile contesa con l'app ufficiale.
CONF_POLL_NORMAL = "poll_normal_min"
CONF_POLL_CHARGING = "poll_charging_min"
DEFAULT_POLL_NORMAL_MIN = 60
DEFAULT_POLL_CHARGING_MIN = 30
# attesa tra la sveglia (localizza) e la lettura realtime forzata, perché l'auto torni online
POLL_WAKE_WAIT = 25
# Alta tensione (HV) e telemetria FRESCA. Scoperta verificata dal vivo 2026-06-22: il canale
# /asr/manager/realtime riporta odometro/SOC/tensione/corrente VERI solo quando l'alta tensione
# è accesa (hVoltageState=1: marcia, ricarica o clima acceso); ad HV spento ritorna uno snapshot
# stantio (odometro vecchio, dumpEnergy=0, totalVoltage=0, totalCurrent=-1000). Non esiste un
# comando "leggero" che forzi un report fresco (confermato dal reverse-engineering della SDK
# nativa Chery): l'unico modo è leggere mentre l'HV è GIÀ acceso. Perciò, appena vediamo l'HV
# acceso, rileggiamo il realtime a raffica per catturare i valori che salgono (odometro/batteria),
# poi smettiamo da soli quando si rispegne. Zero comandi all'auto.
HV_ON_POLL_EVERY = 60   # secondi tra due letture realtime mentre l'alta tensione è accesa
HV_ON_POLL_MAX = 90     # cap di sicurezza al numero di letture ravvicinate (~90 min di marcia)
# RICARICA: quando la spina è collegata l'auto carica per ORE (es. 246 min visti dal vivo 2026-06-23)
# e l'HV è acceso → il realtime ha batteria/corrente/tensione/tempo-residuo VERI. Lo stesso loop
# ravvicinato segue allora l'avanzamento della carica, ma con intervallo più rilassato e cap molto
# più alto della marcia (una carica AC piena può durare diverse ore). Verificato 2026-06-23: ad auto
# in ricarica una lettura realtime dà subito stato_ricarica/corrente_hv/tempo_residuo aggiornati.
CHARGING_POLL_EVERY = 120   # secondi tra due letture realtime mentre la spina è collegata (carica)
CHARGING_POLL_MAX = 300     # cap di sicurezza (~10h: copre una carica AC completa con margine)
# MARCIA (battito di rilevamento): l'auto IN MOVIMENTO non manda push MQTT (verificato dal vivo
# 2026-06-24: a vettura in marcia la sessione MQTT è connessa ma non arriva alcun 5A02 → motore/
# velocità restavano fermi al giorno prima) e il poll periodico "sveglia+leggi" è ogni ~ora. Senza
# un battito dedicato il refresh automatico durante un viaggio non partiva MAI. Questo timer fa SOLO
# una lettura realtime (NESSUN comando, NESSUNA sveglia, zero 12V): appena trova l'HV acceso, la
# stessa lettura arma il follow-up a HV_ON_POLL_EVERY (60s) che poi segue tutto il viaggio. Se il
# follow-up è già attivo (marcia/ricarica) il battito non fa nulla. A vettura ferma è una sola GET
# al cloud ogni intervallo (il realtime torna lo snapshot stantio, scartato): nessun consumo auto.
DRIVE_WATCH_EVERY = 180     # secondi tra due controlli "sei in marcia?" (sola lettura, no comandi)
# attesa nelle macro comfort tra la sveglia (localizza) e l'invio di coolingControl/heatingControl:
# i moduli clima+sedili rispondono solo a vettura DESTA e serve tempo perché la TBOX alimenti il
# bus comfort. Verificato dal vivo 2026-06-21: con ~35s il comando macro va a buon fine; con
# 14s falliva (timeout TBOX↔centraline). Sotto questo valore le macro tornano a dare errore.
MACRO_WAKE_WAIT = 35
# durata del preset comfort (coolingControl/heatingControl usano duration/times = 15 min):
# l'auto lo spegne da sola dopo questo tempo → lo switch macro torna OFF da solo per non
# restare "acceso" a vuoto. +60s di margine.
MACRO_PRESET_S = 15 * 60 + 60

# Anti-doppio-tap: l'auto esegue UN comando alla volta (A00082 = "veicolo occupato").
# Dopo un comando, per questi secondi un nuovo comando ATTUATIVO viene rifiutato con un
# messaggio chiaro invece di accodarsi/floodare. Il lock si libera prima se arriva la
# conferma dall'auto. Cap di sicurezza in caso la conferma non arrivi.
COMMAND_LOCK_S = 12
