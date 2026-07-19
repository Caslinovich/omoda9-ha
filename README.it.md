# Omoda 9 / Jaecoo → Home Assistant

🌐 [English](README.md) · **Italiano**

Porta la tua auto **Omoda 9 / Jaecoo** dentro **Home Assistant**: stato del
veicolo, posizione e comandi, come nell'app ufficiale ma integrati in HA.

> ✅ **Pronto all'uso.** Per partire bastano **email + PIN** del tuo account
> Omoda/Jaecoo (più un **codice OTP** ricevuto via email al primo accesso). VIN e
> certificati vengono rilevati e installati **da soli**. Il pacchetto **non
> contiene alcun dato personale**: token e credenziali restano solo nel *tuo*
> Home Assistant.

> ⚠️ **Software NON ufficiale**, reverse-engineered. Nessuna affiliazione con
> Omoda / Jaecoo / Chery. Fornito "as is", usalo a tuo rischio e solo sul tuo
> veicolo. Vedi [`LICENSE`](LICENSE).

## Cosa puoi fare

- **Stato dell'auto** — porte, serrature, baule, cofano, finestrini, tetto,
  clima, riscaldamento/ventilazione dei sedili e altro, come entità di HA.
- **Posizione / GPS** — un pulsante localizza l'auto (`device_tracker` + sensori
  posizione), anche da parcheggiata.
- **Batteria, velocità, autonomia, km** — si aggiornano da soli quando l'auto è
  **in marcia o in ricarica**; durante la carica il monitoraggio segue
  l'avanzamento.
- **Comandi** — pulsanti per clima, localizzazione, sveglia e altro, che agiscono
  davvero sull'auto.
- **Notifiche** — blueprint opzionale per un avviso quando un comando fallisce.

## Installazione

1. **HACS → menu ⋮ → Custom repositories** → aggiungi l'URL di questo repo,
   categoria **Integration**.
2. Cerca **Omoda 9 / Jaecoo** → **Download** → **riavvia Home Assistant**.
3. **Impostazioni → Dispositivi e servizi → Aggiungi integrazione → Omoda 9**.

## Primo accesso (login)

Tutto avviene **dentro Home Assistant**, niente strumenti esterni:

1. Inserisci **email** e **PIN** dell'account (gli endpoint regionali sono
   opzionali, default Europa). HA invia un **codice OTP** alla tua email.
2. Inserisci il **codice OTP** → HA crea la sessione e scopre i tuoi veicoli.
3. Se hai più auto scegli il **VIN**; se è una sola viene aggiunta direttamente,
   con tutte le entità.

Se in futuro la sessione scade (di solito perché hai aperto l'app ufficiale),
usa i pulsanti **«Richiedi codice OTP» / «Conferma OTP»** (con l'entità testo
«Codice OTP») per rientrare senza riconfigurare nulla.

## Uso quotidiano

- **Non aprire l'app ufficiale** mentre l'integrazione è attiva: stesso account →
  si scollegano (e può servire un nuovo OTP).
- Molte entità sono `unknown` ad **auto in standby** (è normale); dopo un riavvio
  di HA mostrano l'ultimo valore noto.
- Batteria, velocità e km si aggiornano solo **ad auto in marcia o in ricarica**.
  Per una lettura immediata da fermo c'è il pulsante **«Aggiorna stato completo»**,
  che accende il clima ~1 minuto per risvegliare l'auto e poi lo rispegne.

## Aggiornamento

Quando esce una nuova versione: **HACS → Omoda 9 → Update → riavvia Home
Assistant**. Lo storico delle novità è nel [CHANGELOG](CHANGELOG.md).

## Notifiche quando un comando fallisce (opzionale)

L'integrazione fornisce solo le entità: **non invia notifiche da sola**. Se vuoi
un **popup quando un comando all'auto fallisce** (veicolo occupato, non
raggiungibile, sessione scaduta…), importa il blueprint incluso:

[![Importa il blueprint in Home Assistant](https://my.home-assistant.io/badges/blueprint_import.svg)](https://my.home-assistant.io/redirect/blueprint_import/?blueprint_url=https%3A%2F%2Fgithub.com%2FCaslinovich%2Fomoda9-ha%2Fblob%2Fmaster%2Fblueprints%2Fautomation%2Fomoda9%2Fcomando_fallito.yaml)

Poi **Impostazioni → Automazioni → Crea automazione → Da blueprint → _Omoda 9 /
Jaecoo — Avviso comando non riuscito_**. Riconosce solo i veri fallimenti
(ignora ✅ e ⏳), quindi niente falsi allarmi.

## Se qualcosa non funziona

1. **Diagnostica (consigliata):** **Impostazioni → Dispositivi e servizi → Omoda
   9 / Jaecoo → ⋮ → Scarica diagnostica**. È **già anonimizzata** (email, PIN,
   VIN, tUserId e GPS oscurati; di token/certificati appare solo «presente:
   sì/no») → sicura da condividere in una
   [issue](https://github.com/Caslinovich/omoda9-ha/issues).
2. **Log dettagliati:** stessa pagina → **⋮ → Abilita registrazione di debug** →
   riproduci il problema → **Disabilita registrazione di debug**: HA scarica il
   log. PIN, OTP e token **non vengono mai scritti nei log**; l'unico dato
   sensibile possibile è il **VIN** (la diagnostica del punto 1 lo nasconde già).

## Requisiti

- Home Assistant 2024.1.0+ con HACS.
- Un account Omoda/Jaecoo con il veicolo associato (proprietario).
- **Non** serve un broker MQTT locale: l'integrazione si connette **da sola** al
  cloud dell'auto.

---

# Sotto il cofano (tecnico)

Tutto ciò che segue è **automatico**: serve solo per capire il flusso, per il
debug o per portare l'integrazione su una regione non ancora coperta. In
un'installazione normale **non va eseguito nulla a mano**.

### 1. Login e token (OTP)

Il primo accesso conia un **token di sessione** per-account da email + PIN + OTP.
Catena orchestrata dal config flow (codice in `custom_components/omoda9/core/`):

| Passo | Modulo | Cosa fa |
|---|---|---|
| invio OTP | `login_omoda.py invia <email>` | risolve il captcha del gateway (§2) e fa partire il codice via **email** |
| conio token | `prova_token.py <email> <code>` | chiama `/auth/oauth2/token` replicando l'app (cifratura SM4) e salva il token |
| orchestrazione | `session.py` | espone `request_otp()` / `confirm_otp(code)` / `check()` / `refresh()` |

Il token finisce in **`<config>/omoda9_<VIN>_token.json`** (mai nel repo). Finché
il **refresh_token** è valido, `session.refresh()` rinnova la sessione **senza**
nuovo OTP. Un nuovo OTP serve solo se token e refresh muoiono entrambi — tipico
caso: **apertura dell'app ufficiale** (sessione singola lato cloud).

### 2. Captcha (slider) — risolto dentro Home Assistant

L'invio dell'OTP è protetto da uno **slider-captcha**. `captcha_solver.py` lo
risolve **in-process** con **solo `numpy` + `Pillow`** (cross-correlation e
morfologia reimplementate da zero, **niente OpenCV**): così gira anche su **Home
Assistant OS** (musllinux, dove `opencv-python-headless` non ha wheel). Nessuna
interazione utente, nessuna dipendenza pesante.

### 3. Certificati MQTT mutual-TLS — auto-provisioning

La telemetria si connette al broker **EMQX** dell'auto in **mutual-TLS**. I
certificati client (`ca.pem`, `client.pem`, `client.key`) sono **costanti
universali per-regione** — **identiche per tutti gli utenti**, prese dagli asset
**pubblici** dell'APK — **non** dati per-account: l'isolamento tra account è dato
da username/password MQTT e dalle ACL sui topic, come fa l'app ufficiale.

Al primo avvio `coordinator.async_provision_certs()` deobfusca i cert dal bundle
(`custom_components/omoda9/certs/store.json`) e li scrive in
**`<config>/omoda9_<VIN>_certs/`**. Override manuale: il campo **`certs_src`** del
config flow. Per una regione **non** presente nel bundle l'avvio fallisce con un
messaggio che indica dove mettere i cert.

### 4. Provisioning dei comandi (car_token)

Inviare comandi richiede un **car_token per-veicolo** (non lo `userToken` del
BFF). Catena replicata dall'app, gestita da `commands.py`:

```
getTuserId → loginTSP (= car_token) → queryList → setVecDefault(vin)
           → checkPassword(PIN, scene) → comando   (Authorization = car_token)
```

Il **PIN** è quello dell'account. ⚠️ Un PIN **errato** rischia il **lockout**
dell'account: non va indovinato. Il VIN deve risultare tra i veicoli autorizzati
(`authorizeType` 2 = proprietario, 0 = delegato). `provision.py` offre una
**diagnostica in sola lettura** (`diagnose()`) che verifica appartenenza veicolo
e `authorizeType` **senza toccare l'auto**.

### File generati (nel tuo HA, mai nel repo)

- `<config>/omoda9_<VIN>_token.json` — token di sessione per-account.
- `<config>/omoda9_<VIN>_certs/` — certificati mutual-TLS del broker MQTT.

Coperti da `.gitignore`, non lasciano mai la tua installazione.

### Provisioning / login manuale (avanzato, fuori da HA)

Per debug si possono usare gli script CLI in `custom_components/omoda9/core/` con
un Python che abbia i `requirements` del manifest, configurando l'ambiente via
variabili (vedi [`omoda9.env.example`](omoda9.env.example)):

```bash
# 1) invia il codice OTP via email (risolve il captcha)
python3 login_omoda.py invia <email>

# 2) conia il token e salvalo in $OMODA_TOKEN_PATH (default ./token.json)
python3 prova_token.py <email> <codice>

# 3) (opzionale) diagnostica veicolo/autorizzazione — SOLA LETTURA
python3 provision.py
```

Il token così coniato è lo **stesso** file che legge l'integrazione: puntando
`OMODA_TOKEN_PATH` a `<config>/omoda9_<VIN>_token.json` si può sbloccare un setup
anche senza rifare l'OTP dal config flow.

## Licenza

[MIT](LICENSE).

**AVVERTENZA:** questo è un progetto NON UFFICIALE, frutto di reverse-engineering.
NON è affiliato, approvato o supportato da Omoda, Jaecoo, Chery o da alcuna delle
loro società controllate. Tutti i marchi appartengono ai rispettivi proprietari.
Usalo a tuo rischio.
