<!-- logo:inizio -->
<p align="center">
  <picture>
    <source media="(prefers-color-scheme: dark)" srcset="https://raw.githubusercontent.com/Caslinovich/omoda9-ha/master/custom_components/omoda9/brand/dark_logo.png">
    <img src="https://raw.githubusercontent.com/Caslinovich/omoda9-ha/master/custom_components/omoda9/brand/logo.png" alt="OMODA | JAECOO" height="96">
  </picture>
</p>
<!-- logo:fine -->

# Omoda 9 / Jaecoo → Home Assistant

🌐 [English](README.md) · **Italiano**

Porta la tua auto **Omoda 9 / Jaecoo** dentro **Home Assistant**: stato del
veicolo, posizione e comandi, come nell'app ufficiale ma integrati in HA.

> ✅ **Pronto all'uso.** Per partire bastano l'**email (oppure il numero di
> telefono)** del tuo account Omoda/Jaecoo, il **PIN a 4 cifre dell'account**
> (quello che l'app chiede per confermare i comandi a distanza, *non* la password
> di accesso) e un **codice OTP** ricevuto via email o **SMS** al primo accesso. VIN e
> certificati vengono rilevati e installati **da soli**. Il pacchetto **non
> contiene alcun dato personale**: token e credenziali restano solo nel *tuo*
> Home Assistant.

> ⚠️ **Software NON ufficiale**, reverse-engineered. Nessuna affiliazione con
> Omoda / Jaecoo / Chery. Fornito "as is", usalo a tuo rischio e solo sul tuo
> veicolo. Vedi [`LICENSE`](LICENSE).

## Cosa puoi fare

Circa **105 entità**, in breve:

- **Stato dell'auto** — porte, serrature, baule, cofano, finestrini, tetto,
  clima, riscaldamento/ventilazione dei sedili, antifurto e altro, come entità
  di HA.
- **Posizione / GPS** — un pulsante localizza l'auto (`device_tracker` + sensori
  posizione), anche da parcheggiata.
- **Batteria, velocità, autonomia, km, pressione e temperatura delle gomme,
  tensione e corrente della batteria ad alta tensione** — letti dalla telemetria
  dell'auto.
- **Comandi** — clima, «raffredda/riscalda tutto», localizzazione, trova auto,
  antifurto, sveglia, ventilazione dei finestrini: pulsanti e interruttori che
  agiscono davvero sull'auto.
- **Ricarica** — avvio e arresto, ricarica programmata con orario di inizio e
  durata, stato della carica e tempo residuo.
- **Notifiche** — blueprint opzionale per un avviso quando un comando fallisce.

## Installazione

1. **HACS → menu ⋮ → Custom repositories** → aggiungi l'URL di questo repo,
   categoria **Integration**.
2. Cerca **Omoda 9 / Jaecoo** → **Download** → **riavvia Home Assistant**.
3. **Impostazioni → Dispositivi e servizi → Aggiungi integrazione → Omoda 9**.

## Primo accesso (login)

Tutto avviene **dentro Home Assistant**, niente strumenti esterni:

1. Scegli **come accedere**: con l'**email** oppure con il **numero di telefono
   (SMS)**. Se il tuo account Omoda/Jaecoo è registrato col numero e non ha un
   indirizzo email, usa la seconda: con la prima il login non può funzionare.
2. Inserisci le credenziali e il **PIN di controllo del veicolo** (quello a 4
   cifre di cui sopra; gli endpoint regionali sono opzionali, default Europa):
   - **email** → HA invia un **codice OTP** alla tua casella;
   - **telefono** → numero **senza prefisso** e prefisso internazionale in cifre
     (Italia = `39`, senza `+`) → HA fa partire un **SMS** col codice.
3. Inserisci il **codice** ricevuto → HA crea la sessione e scopre i tuoi veicoli.
4. Se hai più auto scegli il **VIN**; se è una sola viene aggiunta direttamente,
   con tutte le entità.

Se in futuro la sessione scade (di solito perché hai aperto l'app ufficiale),
Home Assistant apre una notifica **`<la tua auto>: sessione scaduta`** e segnala
l'integrazione come da riautenticare: vai su **Impostazioni → Dispositivi e
servizi → Omoda 9 / Jaecoo → Riautentica** e scegli **«Inviami un codice nuovo»**
— non c'è nulla da riconfigurare. Nessun codice parte se non lo chiedi tu. Lo
stesso si può fare da una dashboard con i pulsanti **«Richiedi codice OTP» /
«Conferma OTP»** e l'entità testo «Codice OTP».

Se accedi via SMS può comparire anche una terza voce, **«Installa il client TLS
di ripiego»** (~12 MB da scaricare). Serve solo se il filtro anti-bot del server
rifiuta i client di serie: prima prova le altre voci.

## Aggiornamento automatico (di serie è spento)

Un'auto parcheggiata non dice nulla da sola: per tenerla raggiungibile bisogna
**svegliarla** ogni tanto, e questo consuma un po' di batteria 12 V e scollega
l'app ufficiale dall'account. È una scelta tua, quindi parte **spento**:

- Accendi l'interruttore **«Aggiornamento automatico»** (pagina del dispositivo,
  sezione *Configurazione*) perché HA aggiorni la **posizione** da solo. Da lì
  segue anche il **viaggio** mentre guidi e la **carica** mentre l'auto è
  attaccata alla colonnina — ed è lì che batteria, km e i valori dell'alta
  tensione si muovono davvero.
- **⋮ → Configura** decide ogni quanto: **da ferma** (60 min di serie) e
  **attaccata alla colonnina** (30 min); `0` disattiva quell'intervallo. Nella
  stessa pagina anche il nome dell'auto. A parte, un piccolo controllo in **sola
  lettura** gira ogni pochi minuti per accorgersi che hai iniziato a guidare: non
  sveglia mai l'auto.
- A interruttore spento le entità cambiano solo quando è l'auto a mandare
  qualcosa (per esempio mentre la usi) o quando premi un pulsante.

## Uso quotidiano

- **Non aprire l'app ufficiale** mentre l'integrazione è attiva: stesso account →
  si scollegano (e può servire un nuovo OTP).
- Molte entità sono `unknown` ad **auto in standby** (è normale); dopo un riavvio
  di HA mostrano l'ultimo valore noto.
- Batteria, velocità e km si aggiornano solo **ad auto in marcia o in ricarica**:
  l'auto li riporta veri soltanto con l'alta tensione accesa. Un aggiornamento
  automatico ad auto ferma aggiorna la **posizione**, non l'odometro né la
  batteria. Per una lettura immediata c'è il pulsante **«Aggiorna stato
  completo»**, che accende il clima fino a ~2 minuti (di solito meno) per
  risvegliare l'auto e poi lo rispegne.
- Se il **PIN è sbagliato** i comandi risultano falliti e HA apre un avviso di
  riparazione che porta dritto al campo del PIN. Dopo un paio di rifiuti
  l'integrazione smette di interrogare il server: il rischio che l'account Chery
  venga bloccato cala molto, ma non sparisce → **correggi il PIN, non riprovare**.

## Cambiare le impostazioni in seguito

**Impostazioni → Dispositivi e servizi → Omoda 9 / Jaecoo → ⋮ → Riconfigura**
(«Modifica le impostazioni»), tre voci, ognuna chiede solo ciò che cambia:

- **PIN di controllo del veicolo** — per quando i comandi risultano riusciti ma
  l'auto non fa nulla. Non serve alcun codice di verifica.
- **Ricevi il codice via email** — per passare all'email o correggere un errore
  di battitura nell'indirizzo.
- **Ricevi il codice via SMS** — per passare all'SMS o correggere il numero.

In entrambi i casi la sessione in corso resta valida: cambia solo la strada del
prossimo codice.

## Aggiornare l'integrazione

Quando esce una nuova versione: **HACS → Omoda 9 → Update → riavvia Home
Assistant**. Lo storico delle novità è nel [CHANGELOG](CHANGELOG.md).

## Notifiche quando un comando fallisce (opzionale)

L'integrazione fornisce solo le entità: **non invia notifiche da sola**. Se vuoi
un **popup quando un comando all'auto fallisce** (veicolo occupato, non
raggiungibile, sessione scaduta, comando eseguito solo in parte…), importa il
blueprint incluso:

[![Importa il blueprint in Home Assistant](https://my.home-assistant.io/badges/blueprint_import.svg)](https://my.home-assistant.io/redirect/blueprint_import/?blueprint_url=https%3A%2F%2Fgithub.com%2FCaslinovich%2Fomoda9-ha%2Fblob%2Fmaster%2Fblueprints%2Fautomation%2Fomoda9%2Fcomando_fallito.yaml)

Poi **Impostazioni → Automazioni → Crea automazione → Da blueprint → _Omoda 9 /
Jaecoo — Avviso comando non riuscito_**. Riconosce solo i veri fallimenti — gli
esiti positivi e i passaggi intermedi dell'invio vengono ignorati, quindi niente
falsi allarmi — e il popup si chiude da solo appena un comando riesce. Richiede
**HA 2024.10+**.

(La stessa automazione in inglese è
[`failed_command.yaml`](blueprints/automation/omoda9/failed_command.yaml): Home
Assistant non sa tradurre un blueprint, quindi c'è un file per lingua.)

## Se qualcosa non funziona

1. **Diagnostica (consigliata):** **Impostazioni → Dispositivi e servizi → Omoda
   9 / Jaecoo → ⋮ → Scarica diagnostica**. È **già anonimizzata** (email, numero
   di telefono, PIN, VIN, tUserId e GPS oscurati; di token/certificati appare
   solo «presente: sì/no») → sicura da condividere in una
   [issue](https://github.com/Caslinovich/omoda9-ha/issues).
2. **Log dettagliati:** stessa pagina → **⋮ → Abilita registrazione di debug** →
   riproduci il problema → **Disabilita registrazione di debug**: HA scarica il
   log. PIN, OTP e token **non vengono mai scritti nei log**, il numero di
   telefono compare solo mascherato (`***1234`) e le coordinate GPS non vengono
   registrate; il dato da controllare prima di pubblicare è il **VIN** (la
   diagnostica del punto 1 lo nasconde già).

## Requisiti

- Home Assistant 2024.1.0+ con HACS (il menu **Riconfigura** richiede 2024.4+, il
  blueprint opzionale 2024.10+).
- Un account Omoda/Jaecoo con il veicolo associato (**proprietario**). Gli account
  delegati (`authorizeType` 0) non sono collaudati.
- **Non** serve un broker MQTT locale: l'integrazione si connette **da sola** al
  cloud dell'auto.

---

# Sotto il cofano (tecnico)

Tutto ciò che segue è **automatico**: serve solo per capire il flusso, per il
debug o per portare l'integrazione su una regione non ancora coperta. In
un'installazione normale **non va eseguito nulla a mano**.

### 1. Login e token (OTP)

Il primo accesso conia un **token di sessione** per-account dall'identità (email
o telefono) + OTP. Catena orchestrata dal config flow (codice in
`custom_components/omoda9/core/`):

| Passo | Modulo | Cosa fa |
|---|---|---|
| invio OTP (email) | `login_omoda.py invia <email>` | risolve il captcha del gateway (§2) e fa partire il codice via **email** |
| invio OTP (SMS) | `login_omoda.py invia-sms <numero-senza-prefisso> <prefisso>` | idem via `sendSmsCode` — l'unico endpoint dietro un WAF Aliyun che filtra sull'**impronta TLS**, gestito da `tls_client.py` |
| conio token | `prova_token.py <email> <code>` | chiama `/auth/oauth2/token` replicando l'app (cifratura SM4) e salva il token. Per gli account col numero l'identità è la composita `APP-LOGIN@<numero>_<area>` |
| orchestrazione | `session.py` | espone `request_otp()` / `confirm_otp(code)` / `check()` / `refresh()` |

Il **PIN non c'entra con l'accesso**: è l'OTP a coniare il token, il PIN firma
soltanto i comandi (§4).

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

### 4. Autorizzazione dei comandi (taskId)

Ogni comando deve portare un **taskId** coniato da `checkPassword` con il PIN.
Catena replicata dall'app, gestita da `commands.py`:

```
bff_login (= userToken) → queryList → setVecDefault(vin)
        → checkPassword(PIN, scene=0) → taskId → comando  (Authorization = userToken)
```

Nota che i comandi sono firmati con lo **`userToken`** del BFF, non con un
car_token per-veicolo: la catena col car_token (`getTuserId → loginTSP`) esiste
solo nello sperimentale `core/provision.py` e non è usata a runtime.

Il **PIN** è quello a 4 cifre dei comandi dell'account. ⚠️ Un PIN **errato**
rischia il **lockout** dell'account: non va indovinato — ogni rifiuto incrementa
un contatore lato Chery. `core/pin_lockout.py` si ferma dopo 2 rifiuti
consecutivi, ma la finestra è **scorrevole di 10 minuti**: se il PIN sbagliato
resta lì, i tentativi ricominciano. Il VIN deve risultare tra i veicoli autorizzati
(`authorizeType` 2 = proprietario, 0 = delegato). `provision.py` offre una
**diagnostica in sola lettura** (`diagnose()`) che verifica appartenenza veicolo
e `authorizeType` **senza toccare l'auto**.

### File generati (nel tuo HA, mai nel repo)

- `<config>/omoda9_<VIN>_token.json` — token di sessione per-account.
- `<config>/omoda9_<VIN>_certs/` — certificati mutual-TLS del broker MQTT.

Coperti da `.gitignore`, non lasciano mai la tua installazione.

### Provisioning / login manuale (avanzato, fuori da HA)

Per debug si possono usare gli script CLI in `custom_components/omoda9/core/` con
un Python che abbia i `requirements` del manifest. La configurazione arriva da
variabili d'ambiente — l'elenco completo è `ctx_da_environ()` in
[`core/context.py`](custom_components/omoda9/core/context.py) (`OMODA_BFF`,
`TSP_HOST`, `OMODA_TOKEN_PATH`, `OMODA_PHONE`/`OMODA_AREA`, `VIN`, `OMODA_PIN`…).

Vanno lanciati dalla cartella dell'integrazione
(`<config>/custom_components/omoda9/`):

```bash
# 1) invia il codice OTP via email (risolve il captcha)
python3 core/login_omoda.py invia <email>

#    …oppure via SMS, per gli account registrati col numero di telefono
python3 core/login_omoda.py invia-sms <numero-senza-prefisso> <prefisso>

# 2) conia il token e salvalo in $OMODA_TOKEN_PATH (default ./token.json)
python3 core/prova_token.py <email> <codice>
#    per gli account col numero: OMODA_PHONE / OMODA_AREA / OMODA_OTP nell'ambiente

# 3) (opzionale) diagnostica veicolo/autorizzazione — SOLA LETTURA, contatta il cloud
python3 -m core.provision diagnose
```

⚠️ `provision.py` usa import relativi di pacchetto: va lanciato con `-m` come
sopra, e l'argomento `diagnose` è obbligatorio — senza argomenti esegue un
**auto-test offline con dati finti**, non contatta nulla.

Il token così coniato è lo **stesso** file che legge l'integrazione: puntando
`OMODA_TOKEN_PATH` a `<config>/omoda9_<VIN>_token.json` si può sbloccare un setup
anche senza rifare l'OTP dal config flow.

## Licenza

[MIT](LICENSE).

**AVVERTENZA:** questo è un progetto NON UFFICIALE, frutto di reverse-engineering.
NON è affiliato, approvato o supportato da Omoda, Jaecoo, Chery o da alcuna delle
loro società controllate. Tutti i marchi appartengono ai rispettivi proprietari.
Usalo a tuo rischio.
