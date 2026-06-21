"""Costanti del custom component Omoda 9 / Jaecoo."""

DOMAIN = "omoda9"
PLATFORMS = ["sensor", "binary_sensor", "button", "lock", "switch", "climate",
             "number", "cover", "device_tracker", "text"]

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
