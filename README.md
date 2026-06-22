# Omoda 9 / Jaecoo → Home Assistant

Custom integration **HACS** che collega un'auto **Omoda 9 / Jaecoo** (piattaforma
telematica Chery) a **Home Assistant**. Progetto di reverse-engineering.

- **Telemetria** — connessione mutual-TLS al broker MQTT cloud dell'auto; gli
  eventi diventano entità HA (porte, serrature, baule, cofano, finestrini, tetto,
  clima, riscaldamento/ventilazione sedili…).
- **Posizione/GPS** — comando di localizzazione → `device_tracker` + sensori
  posizione (on-demand, anche ad auto parcheggiata).
- **Batteria / velocità / odometro** — disponibili ad auto **in marcia**.
- **Comandi** — pulsanti (clima on/off, localizza, sveglia, ecc.) che agiscono
  sull'auto coniando un `taskId` proprio.
- **Sessione/OTP** — config flow per-utente + entità di recupero sessione.

> ✅ **Pronto all'uso, condivisibile da chiunque.** Per partire bastano **email +
> PIN** del tuo account Omoda/Jaecoo (più un **codice OTP** ricevuto via email al
> primo accesso). VIN, tUserId e certificati MQTT vengono rilevati/installati
> **automaticamente**. Il pacchetto **non contiene alcun dato per-account**: i soli
> segreti (token, credenziali) restano nel *tuo* Home Assistant.

> ⚠️ **Software NON ufficiale**, reverse-engineered. Nessuna affiliazione con
> Omoda / Jaecoo / Chery. Fornito "as is", usalo a tuo rischio e solo sul tuo
> veicolo. Vedi [`LICENSE`](LICENSE).

## Installazione (HACS)

1. HACS → menu ⋮ → **Custom repositories** → aggiungi l'URL di questo repo,
   categoria **Integration**.
2. Cerca **Omoda 9 / Jaecoo** → **Download** → **riavvia Home Assistant**.
3. **Impostazioni → Dispositivi e servizi → Aggiungi integrazione → Omoda 9** e
   segui il config flow: **email + PIN** → **codice OTP** ricevuto via email. Fine.

## Login (OTP) — interamente in Home Assistant, solo email + PIN

Il login avviene **dal config flow**, senza strumenti esterni né un token
pre-esistente, e chiede **solo l'email e il PIN** dell'account: VIN e tUserId
vengono **rilevati automaticamente** dal backend.

1. **Primo step:** inserisci `email` e `PIN` (gli endpoint regionali sono
   opzionali, default Europa). Alla conferma HA risolve **da solo** il captcha
   del gateway e invia un **codice OTP alla tua email**.
2. **Secondo step:** inserisci il codice ricevuto → HA conia il token e
   **scopre** il tUserId e i veicoli dell'account.
3. **Se l'account ha più auto**, scegli il VIN; se è una sola, viene aggiunta
   direttamente. Il dispositivo è creato con tutte le entità.

Quando in futuro la sessione scade (tipicamente perché è stata aperta l'app
ufficiale), usa i pulsanti **«Richiedi codice OTP»** / **«Conferma OTP»** (con
l'entità *testo* «Codice OTP») per rifare il login senza riconfigurare.

---

## Come funziona — provisioning e autenticazione (sotto il cofano)

Tutto ciò che segue è **automatico**: serve solo per capire il flusso, per il
debug, o per portare l'integrazione su una regione non ancora coperta. Nessuno di
questi passi va eseguito a mano in un'installazione normale.

### 1. Login e token (OTP)

Il primo accesso conia un **token di sessione** per-account a partire da email +
PIN + un codice OTP via email. La catena (orchestrata dal config flow, codice in
`custom_components/omoda9/core/`):

| Passo | Modulo | Cosa fa |
|---|---|---|
| invio OTP | `login_omoda.py invia <email>` | risolve il captcha del gateway (vedi §2) e fa partire il codice via **email** |
| conio token | `prova_token.py <email> <code>` | chiama `/auth/oauth2/token` replicando l'app (codice cifrato SM4) e salva il token |
| orchestrazione | `session.py` | espone `request_otp()` / `confirm_otp(code)` / `check()` / `refresh()`; lancia i due script come sottoprocesso |

Il token viene scritto in **`<config>/omoda9_<VIN>_token.json`** (nel *tuo* Home
Assistant, mai nel repo). Finché il **refresh_token** è valido, `session.refresh()`
rinnova la sessione **senza** nuovo OTP né captcha. Un nuovo OTP serve solo se
sia il token sia il refresh muoiono — caso tipico: **apertura dell'app ufficiale**
(sessione singola lato cloud).

### 2. Captcha (slider) — risolto dentro Home Assistant

L'invio dell'OTP è protetto da uno **slider-captcha** (`/api/code/create` →
`/api/code/check`). `captcha_solver.py` lo risolve **in-process** con **solo
`numpy` + `Pillow`** (cross-correlation e morfologia reimplementate da zero,
**niente OpenCV/cv2**): così gira anche su **Home Assistant OS** (musllinux, dove
`opencv-python-headless` non ha wheel). Nessuna interazione utente, nessuna
dipendenza pesante.

### 3. Certificati MQTT mutual-TLS — auto-provisioning

La telemetria si connette al broker **EMQX** dell'auto in **mutual-TLS**. I
certificati client (`ca.pem`, `client.pem`, `client.key`) sono **costanti
universali per-regione** — **identiche per tutti gli utenti**, prese verbatim
dagli asset **pubblici** dell'APK (`Subject: CN=client`) — **non** dati
per-account: l'isolamento tra account è dato da username/password MQTT (clientId +
md5) e dalle ACL sui topic, esattamente come fa l'app ufficiale.

Al primo avvio `coordinator.async_provision_certs()` →
`cert_bundle.decrypt_region(<host_mqtt>)` deobfusca i cert dal bundle
(`custom_components/omoda9/certs/store.json`) e li scrive in
**`<config>/omoda9_<VIN>_certs/`**. Override manuale: il campo **`certs_src`** del
config flow (cartella con i cert già pronti), oppure copiali a mano in quella
dir. Per una regione **non** presente nel bundle l'avvio fallisce con un messaggio
che indica dove mettere i cert.

### 4. Provisioning dei comandi (car_token)

Inviare comandi all'auto richiede un **car_token per-veicolo** (non lo `userToken`
del BFF). La catena replicata dall'app è:

```
getTuserId → loginTSP (= car_token) → queryList → setVecDefault(vin)
           → checkPassword(PIN, scene) → comando   (Authorization = car_token)
```

Gestita da `commands.py`; il **PIN** è quello dell'account. ⚠️ Un PIN **errato**
rischia il **lockout** dell'account: non va indovinato. Il VIN deve risultare tra
i veicoli autorizzati (`authorizeType` 2 = proprietario, 0 = delegato).
`provision.py` offre una **diagnostica in sola lettura** (`diagnose()`) per
verificare appartenenza veicolo e `authorizeType` **senza toccare l'auto**.

### File generati (nel tuo HA, mai nel repo)

- `<config>/omoda9_<VIN>_token.json` — token di sessione per-account.
- `<config>/omoda9_<VIN>_certs/` — certificati mutual-TLS del broker MQTT.

Sono coperti da `.gitignore`; non lasciano mai la tua installazione.

### Provisioning / login manuale (avanzato, fuori da HA)

Per debug si possono usare gli script CLI in `custom_components/omoda9/core/` con
un Python che abbia i `requirements` del manifest, configurando l'ambiente via
variabili (vedi [`omoda9.env.example`](omoda9.env.example): `OMODA_BFF`,
`OMODA_TOKEN_PATH`, `VIN`, `TUSERID`, `OMODA_PIN`, endpoint regionali…):

```bash
# 1) invia il codice OTP via email (risolve il captcha)
python3 login_omoda.py invia <email>

# 2) conia il token e salvalo in $OMODA_TOKEN_PATH (default ./token.json)
python3 prova_token.py <email> <codice>

# 3) (opzionale) diagnostica veicolo/autorizzazione — SOLA LETTURA, non tocca l'auto
python3 provision.py
```

Il token così coniato è lo **stesso** file che legge l'integrazione: puntando
`OMODA_TOKEN_PATH` a `<config>/omoda9_<VIN>_token.json` si può sbloccare un setup
anche senza rifare l'OTP dal config flow.

## Aggiornamento

Quando esce una nuova release: **HACS → Omoda 9 → Update → riavvia Home Assistant**.

## Requisiti

- Home Assistant 2024.1.0+ con HACS.
- Un account Omoda/Jaecoo con il veicolo associato (proprietario).
- Un broker MQTT raggiungibile da Home Assistant (es. add-on Mosquitto).

## Note d'uso

- **Non aprire l'app ufficiale Omoda/Jaecoo** mentre l'integrazione è attiva:
  stesso clientId → si scollegano (e può invalidare il token → nuovo OTP).
- Molte entità sono `unknown` ad **auto in standby** (atteso); mostrano l'ultimo
  valore noto dopo un riavvio di HA (persistenza `RestoreEntity`).
- Batteria/velocità/odometro arrivano **solo ad auto in marcia**.

## Risoluzione problemi — log e diagnostica

Se qualcosa non funziona, ecco **cosa raccogliere e inviare** per farsi aiutare (o
aprire una [issue](https://github.com/Caslinovich/omoda9-ha/issues)).

### 1. Diagnostica (consigliata) — un clic, già anonimizzata

**Impostazioni → Dispositivi e servizi → Omoda 9 / Jaecoo →** menù **⋮ → Scarica
diagnostica**. Scarichi un file con stato sessione, parametri, presenza di
token/certificati e l'ultima telemetria ricevuta. È **sicuro da condividere**: email,
PIN, VIN, tUserId e la **posizione GPS** sono oscurati automaticamente, e di token e
certificati appare solo «presente: sì/no», mai il contenuto.

### 2. Log dettagliati (quando serve vedere l'errore preciso)

Nella stessa pagina dell'integrazione: menù **⋮ → Abilita registrazione di debug** →
**riproduci il problema** (es. premi il comando che fallisce) → torna e premi
**Disabilita registrazione di debug**: Home Assistant **scarica da solo** il file di log
con tutto il dettaglio dell'integrazione.

In alternativa, il log generale di HA è in **Impostazioni → Sistema → Registri →
Scarica registro completo**.

> I moduli di login girano isolati e con l'output catturato: **PIN, codice OTP e token
> non vengono mai scritti nei log**. L'unico dato un po' sensibile che può comparire nel
> log di debug è il **VIN** — se vuoi, oscuralo prima di inviare il file (la
> *diagnostica* del punto 1 lo nasconde già da sola).

## Notifiche di errore (blueprint opzionale)

L'integrazione fornisce solo le entità: **non invia notifiche da sola** (per non essere
invadente). Se vuoi un **popup quando un comando all'auto fallisce** (veicolo occupato,
auto non raggiungibile, rate-limit, errore di rete, sessione scaduta…), importa il
blueprint incluso:

[![Importa il blueprint in Home Assistant](https://my.home-assistant.io/badges/blueprint_import.svg)](https://my.home-assistant.io/redirect/blueprint_import/?blueprint_url=https%3A%2F%2Fgithub.com%2FCaslinovich%2Fomoda9-ha%2Fblob%2Fmaster%2Fblueprints%2Fautomation%2Fomoda9%2Fcomando_fallito.yaml)

Poi **Impostazioni → Automazioni → Crea automazione → Da blueprint → _Omoda 9 / Jaecoo —
Avviso comando non riuscito_**. Puoi attivare il popup in Home Assistant e/o aggiungere un
push sul telefono. Riconosce solo i veri fallimenti: ignora gli esiti positivi (✅), "in
corso" (⏳) e i messaggi intermedi, quindi niente falsi allarmi.

## Stato / roadmap

- ✅ Telemetria, posizione/GPS, batteria/velocità, comandi, sessione/OTP.
- ✅ **OTP da zero su Home Assistant OS** (v0.2.1): il captcha è risolto
  interamente in HA con `numpy`+`Pillow` (niente più `opencv`/`cv2`), quindi il
  login dal config flow funziona su qualsiasi installazione, anche senza un token
  preesistente. Con un token valido la sessione si auto-rinnova senza captcha.
- ✅ **Provisioning automatico dei certificati** mutual-TLS (v0.2.4): cert client
  EMQX universali per-regione auto-installati al setup → onboarding solo email+PIN,
  senza estrarre nulla a mano.
- ✅ **Persistenza stato al riavvio di HA** (v0.2.5–v0.2.6): posizione, batteria,
  velocità e tutte le entità di stato ripristinano l'ultimo valore noto via
  `RestoreEntity`/`RestoreSensor`.

## Licenza

[MIT](LICENSE). Progetto indipendente, non ufficiale.
