# Novità di Omoda 9 / Jaecoo per Home Assistant

Cosa cambia a ogni aggiornamento, spiegato in parole semplici.
Le voci più recenti sono in alto. Le versioni indicano la "puntata"
dell'integrazione: aggiorna da **HACS → Omoda 9 / Jaecoo → Aggiorna**.

## [Non rilasciato]

### 🇮🇹 Italiano

- **Aggiornamento di manutenzione: per te non cambia nulla.** Non ci sono nuove funzioni né
  correzioni visibili. Questa versione aggiunge solo strumenti interni che aiutano chi sviluppa
  l'integrazione a capire meglio i problemi segnalati. Restano spenti e non influiscono in alcun
  modo sul funzionamento né sui consumi: puoi aggiornare tranquillamente.

### 🇬🇧 English

- **Maintenance update: nothing changes for you.** No new features and no visible fixes. This
  release only adds internal tooling that helps the integration's developer investigate reported
  problems. It stays switched off and has no effect whatsoever on behaviour or resource usage —
  you can update safely.

## v1.5.27 — 2026-07-19

### 🇮🇹 Italiano

- **Non ti chiede più di rifare l'accesso quando è solo internet che fa i capricci.** Se il
  collegamento con il server dell'auto cadeva per un attimo, poteva comparire la richiesta di
  rientrare con un nuovo codice via email — inutile, perché la sessione era ancora buona. Ora
  l'integrazione distingue "sessione davvero scaduta" da "problema di rete passeggero" e ti
  disturba solo quando serve per davvero.
- **Un accesso in meno da rifare a mano.** In alcuni casi la sessione poteva essere rinnovata da
  sola, in silenzio, ma l'integrazione non ci provava e ti chiedeva subito il codice via email.
  Ora tenta prima il rinnovo automatico: spesso non dovrai fare nulla.
- **Basta con il falso "PIN sbagliato".** Quando l'auto rifiutava un comando per motivi che col
  PIN non c'entrano nulla (per esempio l'account non ha i permessi su quella vettura), ti veniva
  comunque detto che il PIN era errato e ti veniva chiesto di cambiarlo. Peggio: quel rifiuto
  veniva contato come tentativo sbagliato e ti avvicinava al blocco del PIN. Ora ogni rifiuto
  viene riconosciuto per quello che è: il messaggio dice la causa vera, il PIN corretto non viene
  più messo in discussione e non si consumano tentativi per colpa di errori che non sono tuoi.
- **Il PIN non si vede più in chiaro.** Nelle schermate per cambiare il PIN dei comandi, il codice
  appariva scritto per esteso. Ora è mascherato con i pallini, come una normale password.
- **Il codice via email è più al riparo.** Email e codice di verifica non vengono più passati in un
  modo che, su alcuni sistemi, poteva renderli visibili ad altri programmi in esecuzione. Inoltre,
  quando spegni o rimuovi l'integrazione, PIN ed email non restano più in memoria.
- **Il file di diagnostica non rivela più dove tieni i certificati.** Se lo invii per farti aiutare,
  ora il percorso della cartella (che spesso contiene il tuo nome utente) viene oscurato come già
  accadeva per email, targa e posizione.
- **Il nome del sensore "Dati auto aggiornati" ora è tradotto** anche in italiano e in inglese,
  come tutti gli altri.
- **Per chi ci aiuta a trovare i problemi:** ora è possibile chiedere a Home Assistant i log
  dettagliati dell'integrazione dalla sua pagina, senza smanettare nei file di configurazione.

### 🇬🇧 English

- **No more "please sign in again" when it's just the internet acting up.** If the connection to
  the car's server dropped for a moment, you could be asked to sign in again with a new email
  code — pointless, since the session was still fine. The integration now tells a genuinely
  expired session apart from a passing network glitch, and only bothers you when it really matters.
- **One less sign-in to do by hand.** In some cases the session could have been renewed silently on
  its own, but the integration didn't try and asked you for the email code straight away. It now
  attempts the automatic renewal first: often you won't have to do anything.
- **No more false "wrong PIN".** When the car refused a command for reasons that have nothing to do
  with the PIN (for example, the account lacks permissions on that vehicle), you were still told
  the PIN was wrong and asked to change it. Worse, that refusal counted as a failed attempt and
  pushed you closer to having your PIN locked. Every refusal is now recognised for what it is: the
  message states the real cause, a correct PIN is no longer questioned, and attempts are no longer
  used up because of errors that aren't yours.
- **Your PIN is no longer shown in plain text.** On the screens for changing the command PIN, the
  code was displayed in full. It is now masked with dots, like any normal password.
- **The email code is better protected.** Your email address and verification code are no longer
  passed in a way that, on some systems, could make them visible to other running programs. Also,
  when you shut down or remove the integration, the PIN and email no longer linger in memory.
- **The diagnostics file no longer reveals where you keep your certificates.** If you send it in to
  get help, the folder path (which often contains your username) is now hidden, just as your email,
  VIN and location already were.
- **The "Car data updated" sensor name is now translated** into both Italian and English, like all
  the others.
- **For those helping us track down problems:** you can now ask Home Assistant for the integration's
  detailed logs from its own page, without editing configuration files by hand.

## v1.5.26 — 2026-07-19

### 🇮🇹 Italiano

- **Meno rischio di bloccare il PIN dell'auto.** Se due richieste partivano nello stesso momento
  (per esempio premi "Sveglia" due volte, o un comando mentre l'auto si sta svegliando), potevano
  provare il codice di sicurezza in parallelo e "consumare" più tentativi del previsto: con un PIN
  sbagliato si rischiava di avvicinarsi al blocco dell'account. Ora le richieste si mettono in fila
  e viene rispettato il limite di tentativi che l'integrazione si è data.
- **Reinserire lo stesso PIN ora sblocca davvero.** Se dopo un errore riconfermavi il PIN identico
  a prima (perché in realtà il problema non era il PIN), il blocco di sicurezza restava attivo e i
  comandi continuavano a non partire per diversi minuti. Ora, ogni volta che confermi il PIN
  — dall'avviso di riparazione o dalle impostazioni — si riparte puliti.
- **Se la sveglia dell'auto fallisce, ora te lo dice.** Quando il tentativo di risveglio non
  riusciva per PIN o sessione scaduta, l'errore restava nascosto nei log: nessun avviso, nessuna
  richiesta di reinserire il codice. Ora compare l'avviso giusto, esattamente come quando premi un
  pulsante: correggi il PIN o rifai l'accesso e riprovi.
- **Niente più letture in sottofondo dopo aver spento l'integrazione.** Se ricaricavi o rimuovevi
  l'integrazione mentre l'auto era in carica, un controllo automatico poteva restare acceso e
  continuare a interrogare il server anche dopo. Ora si ferma insieme a tutto il resto.
- **L'interruttore "Aggiornamento automatico" ora ferma tutto.** Spegnendolo mentre l'auto era
  sotto carica, il controllo ravvicinato della ricarica proseguiva lo stesso. Ora quando è spento
  l'integrazione non contatta più l'auto da sola, come ci si aspetta.

### 🇬🇧 English

- **Less risk of locking your car's PIN.** If two requests started at the same moment (for example
  pressing "Wake" twice, or sending a command while the car is waking up), they could try the
  security code in parallel and burn more attempts than intended — with a wrong PIN that meant
  getting closer to an account lockout. Requests are now queued and the attempt limit the
  integration sets for itself is properly respected.
- **Re-entering the same PIN now really unblocks it.** If after an error you confirmed the very
  same PIN (because the problem wasn't the PIN after all), the safety block stayed active and
  commands kept failing for several minutes. Now every time you confirm the PIN — from the repair
  notice or from the settings — it starts fresh.
- **If waking the car fails, you're now told.** When the wake-up attempt failed because of the PIN
  or an expired session, the error stayed hidden in the logs: no notice, no request to re-enter the
  code. Now you get the proper notice, exactly as when you press a button: fix the PIN or sign in
  again, then retry.
- **No more background readings after switching the integration off.** If you reloaded or removed
  the integration while the car was charging, an automatic check could stay alive and keep querying
  the server afterwards. It now stops together with everything else.
- **The "Automatic update" switch now stops everything.** Turning it off while the car was charging
  did not stop the close-interval charge tracking. Now, when it is off, the integration no longer
  contacts the car on its own — as you would expect.

## v1.5.25 — 2026-07-11

### 🇮🇹 Italiano

- **Comandi più veloci.** Prima ogni comando rifaceva da capo la verifica del PIN col server: ora
  l'autorizzazione ottenuta viene riusata per una decina di minuti, quindi la maggior parte dei
  comandi parte subito. Se l'auto la rifiuta perché scaduta, l'integrazione la rinnova e riprova
  da sola, senza mostrarti un errore.
- **Niente più "un altro comando è in corso".** L'auto esegue un comando alla volta: prima, se ne
  premevi un secondo mentre il primo era in volo, veniva rifiutato con un errore. Ora **si mette in
  coda** e parte da solo appena l'auto ha confermato il precedente.
- **Sicurezza e riservatezza.** Tre correzioni: l'integrazione non scrive più su disco i dati grezzi
  dell'auto (che contenevano telaio e posizione GPS); il file di diagnostica che puoi condividere per
  chiedere aiuto **non contiene più il numero di telaio**; i file con le credenziali di accesso sono
  ora leggibili solo dal proprietario.
- **Configurazione iniziale: correggere l'email adesso funziona.** Se sbagliavi a digitare l'email,
  ogni nuovo tentativo continuava a usare quella vecchia e falliva finché non riavviavi Home
  Assistant. Ora ogni tentativo usa l'email che hai appena scritto. In più, se il codice non parte,
  ora **vedi scritto il motivo** sotto al modulo (prima non appariva da nessuna parte).
- **Basta codice vecchio dopo un aggiornamento.** In certi casi, dopo un update, Home Assistant
  continuava a far girare la versione precedente di alcune parti interne. Ora vengono ricaricate
  sempre da zero: aggiornare e riavviare basta.
- **Tolto un doppione tra gli indicatori del motore.** C'erano due voci per lo stato del motore
  ("Motore" e "Motore acceso") che mostravano la stessa identica informazione: ne resta una sola
  ("Motore"), quella storica. Nessuna funzione persa, solo un po' di ordine in più.
- **Diagnosi più precisa quando un comando viene rifiutato per il PIN.** Quando l'auto non accetta
  il codice di sicurezza dei comandi, ora l'integrazione **mostra e registra il codice esatto**
  restituito dal server. Serve a distinguere con certezza un vero "PIN sbagliato" da altre cause
  (permessi del veicolo, problema temporaneo del server): utile se, dopo aver corretto il PIN, i
  comandi continuassero a non partire.

### 🇬🇧 English

- **Faster commands.** Every command used to redo the full PIN check with the server: the
  authorisation is now reused for about ten minutes, so most commands go straight through. If the
  car rejects it as expired, the integration renews it and retries on its own, without showing you
  an error.
- **No more "another command is still in progress".** The car runs one command at a time: before, a
  second press while the first was in flight was rejected with an error. Now it **waits its turn**
  and runs as soon as the car has confirmed the previous one.
- **Security and privacy.** Three fixes: the integration no longer writes the raw vehicle data to
  disk (it contained the VIN and the GPS position); the diagnostics file you can share when asking
  for help **no longer contains the VIN**; the files holding your access credentials are now
  readable by their owner only.
- **Setup: correcting your email now works.** If you mistyped your email, every retry kept using the
  old one and failed until you restarted Home Assistant. Each attempt now uses the email you just
  typed. Also, when the code can't be sent, **the reason is now shown** under the form (previously
  it appeared nowhere).
- **No more old code running after an update.** In some cases, after an update, Home Assistant kept
  running the previous version of some internal parts. They are now always reloaded from scratch:
  updating and restarting is enough.
- **Removed a duplicate engine indicator.** There were two entries for the engine state ("Engine"
  and "Engine running") showing the exact same information: only one remains ("Engine"), the
  original. No functionality lost, just a bit tidier.
- **More precise diagnosis when a command is rejected because of the PIN.** When the car doesn't
  accept the command security code, the integration now **shows and logs the exact code** returned
  by the server. This tells a genuine "wrong PIN" apart from other causes (vehicle permissions, a
  temporary server issue): useful if commands still won't go through after you've corrected the PIN.

### 🙏 Grazie / Credits

Le migliorie di questa versione (velocità dei comandi, coda, correzioni di sicurezza e privacy,
setup, ricarica del codice dopo un update) nascono dal lavoro di **[JackRonan](https://github.com/JackRonan)**
nel suo fork inglese [omoda-jaecoo-ha](https://github.com/JackRonan/omoda-jaecoo-ha), da cui sono
state riportate qui. Grazie di cuore per averle trovate, risolte e condivise. — *The improvements in
this release (command speed, queueing, security and privacy fixes, setup, code reloading after an
update) come from **JackRonan**'s work on his English fork, and were ported back here. Thank you!*

## v1.5.24 — 2026-07-06

### 🇮🇹 Italiano

- **Risolto il problema più insidioso: comandi che sembravano riusciti ma l'auto non faceva
  nulla.** Se il **PIN a 4 cifre dei comandi remoti** è sbagliato, l'auto rifiuta ogni comando:
  finora però l'interruttore in Home Assistant restava sul "fatto" e sembrava tutto a posto
  (mentre finestrini, clima, serratura ecc. non si muovevano). Ora, in questo caso, **l'interruttore
  torna subito allo stato reale** e compare un chiaro messaggio: **«PIN comandi errato»**.
- **Puoi correggere il PIN senza dover eliminare e riaggiungere l'integrazione.** Compare un avviso
  di **riparazione** di Home Assistant (Impostazioni → il classico avviso in alto) che, con un clic,
  ti fa **inserire il PIN corretto** e sistema tutto da solo. In alternativa trovi la stessa cosa in
  **Impostazioni → Dispositivi e servizi → Omoda 9 → Riconfigura**. Non serve alcun codice via email:
  il PIN dei comandi non c'entra con l'accesso. (Consiglio: non insistere con un PIN errato, per non
  rischiare il blocco dell'account.)
- **Se l'accesso scade (capita se apri l'app ufficiale sul telefono) ora te lo dice chiaramente.**
  Prima l'unico modo per rimettere a posto la sessione era cercare dei pulsanti "nascosti"; ora
  Home Assistant mostra l'avviso standard **«Ri-autenticazione necessaria»**: premi, ricevi un
  **codice via email** e lo inserisci — e i dati tornano. I vecchi pulsanti OTP restano comunque
  disponibili come riserva.

### 🇬🇧 English

- **Fixed the nastiest problem: commands that looked successful while the car did nothing.** If the
  **4-digit remote-command PIN** is wrong, the car rejects every command — but until now the switch
  in Home Assistant stayed on "done" and everything looked fine (while windows, climate, lock, etc.
  didn't move). Now, in this case, **the switch snaps back to its real state** and a clear message
  appears: **"Wrong command PIN"**.
- **You can fix the PIN without deleting and re-adding the integration.** A Home Assistant **repair**
  notice appears (Settings → the usual banner at the top) that, with one click, lets you **enter the
  correct PIN** and sorts everything out. Alternatively you'll find the same under **Settings →
  Devices & services → Omoda 9 → Reconfigure**. No email code is needed: the command PIN has nothing
  to do with logging in. (Tip: don't keep retrying with a wrong PIN, to avoid locking the account.)
- **If your session expires (which happens if you open the official phone app) it now tells you
  clearly.** Previously the only way to restore the session was to hunt for "hidden" buttons; now
  Home Assistant shows the standard **"Re-authentication required"** notice: click it, get a **code
  by email**, enter it — and the data comes back. The old OTP buttons remain available as a fallback.

## v1.5.23 — 2026-07-06

### 🇮🇹 Italiano

- **Batteria e chilometri restano aggiornati anche ad auto ferma, e la macchina viene "svegliata"
  molto meno di prima.** Abbiamo scoperto che l'auto resta raggiungibile dal cloud per ore dopo
  averla usata: in questa finestra l'integrazione legge batteria, chilometri, autonomia e gomme
  **in sola lettura, senza svegliarla**. Quindi ora la sveglia (che consuma un pochino la batteria
  da 12V e può dare fastidio all'app ufficiale sul telefono) parte **solo quando serve davvero**,
  cioè quando l'auto è effettivamente "addormentata"; se è già raggiungibile, i dati si aggiornano
  da soli senza alcun risveglio. È stato aggiunto anche un nuovo indicatore **"Dati auto
  aggiornati"** che mostra a che ora risale l'ultimo dato ricevuto dall'auto, così sai quanto è
  fresco quello che vedi. Migliorato infine il riconoscimento della marcia (in certi casi l'auto
  risultava ferma pur essendo in movimento). Tutto rigorosamente **a sola lettura**.
- **Gli interruttori non mostrano più un finto "fatto" quando l'auto rifiuta il comando.** Se
  invii un comando (chiudi, clima, serratura…) mentre l'auto sta già eseguendo qualcos'altro, è
  occupata e non lo esegue: prima l'interruttore restava acceso come se fosse andato a buon fine
  e bisognava aspettare diversi secondi per riprovare. Ora l'interruttore **torna subito allo
  stato reale**, compare un avviso chiaro («auto occupata, riprova tra qualche secondo») e puoi
  **ritentare immediatamente**. Lo stesso vale per gli altri rifiuti dell'auto (funzione non
  consentita su questa vettura, sessione da rifare): niente più falsi "eseguito".
- **Nuovi indicatori e autonomia totale più realistica.** Aggiunti quattro nuovi indicatori
  verificati dal vivo: **Motore acceso**, **Alta tensione attiva**, **Avviso carburante basso**
  e **Avviso ricarica necessaria**. In cambio abbiamo tolto alcuni indicatori che questa vettura
  non trasmette proprio (restavano per sempre "sconosciuto" e non facevano che confondere:
  temperatura abitacolo, alcuni contachilometri parziali, potenza di ricarica, velocità media,
  consumo istantaneo, tempi di ricarica rapida). Infine l'**Autonomia totale** ora è calcolata
  come **elettrica + benzina** (prima usava un valore del cruscotto che, verificato sul campo,
  restava fisso e non seguiva la carica) → il numero mostrato è finalmente coerente con lo stato
  reale di batteria e serbatoio.

### 🇬🇧 English

- **Battery and mileage stay fresh even while the car is parked, and the car is "woken up" far less
  than before.** We found that the car stays reachable from the cloud for hours after you use it:
  during that window the integration reads battery, mileage, range and tyres **read-only, without
  waking it**. So the wake-up (which slightly uses the 12V battery and can interfere with the
  official phone app) now happens **only when actually needed** — i.e. when the car is genuinely
  asleep; if it's already reachable, the data refreshes on its own with no wake-up at all. We also
  added a new **"Car data updated"** indicator showing the time of the last data received from the
  car, so you know how fresh what you see is. Driving detection was also improved (in some cases the
  car looked stationary while actually moving). Everything strictly **read-only**.
- **Switches no longer show a fake "done" when the car rejects the command.** If you send a
  command (close, climate, lock…) while the car is already doing something else, it's busy and
  won't run it: previously the switch stayed on as if it had succeeded, and you had to wait
  several seconds before retrying. Now the switch **snaps back to its real state**, a clear notice
  appears ("car busy, try again in a few seconds") and you can **retry right away**. The same
  applies to the car's other rejections (feature not allowed on this vehicle, session needs
  re-login): no more false "executed".
- **New indicators and a more realistic total range.** Added four new live-verified indicators:
  **Engine running**, **High voltage active**, **Low fuel warning** and **Charge needed warning**.
  In exchange we removed a few indicators this vehicle simply doesn't transmit (they stayed
  "unknown" forever and only caused confusion: cabin temperature, some trip odometers, charging
  power, average speed, instant consumption, fast-charge times). Finally, **Total range** is now
  computed as **electric + petrol** (it previously used a dashboard value that, verified in the
  field, stayed fixed and didn't follow the charge) → the number shown is finally consistent with
  the real battery and tank state.

## v1.5.22 — 2026-06-24

### 🇮🇹 Italiano

- **Ora i dati dell'auto si aggiornano da soli mentre guidi.** Prima, durante un viaggio, valori
  come batteria, chilometri percorsi e autonomia restavano fermi finché non premevi a mano il
  pulsante "Aggiorna stato completo": l'auto in movimento, infatti, non invia aggiornamenti
  spontanei. Adesso l'integrazione se ne accorge da sola e, mentre sei in marcia, aggiorna i dati
  da sola circa ogni minuto, senza che tu debba toccare niente. A vettura ferma o in ricarica non
  cambia nulla rispetto a prima. Tutto questo avviene **solo a lettura**: non viene inviato alcun
  comando all'auto e non si consuma la batteria. Funziona con l'interruttore "Aggiornamento
  automatico" acceso (come già era).

### 🇬🇧 English

- **Your car's data now updates by itself while you drive.** Until now, during a trip, values like
  battery, distance travelled and range stayed frozen until you manually pressed the "Refresh full
  status" button: a moving car doesn't send updates on its own. Now the integration notices this by
  itself and, while you're driving, refreshes the data roughly every minute with no action from you.
  When the car is parked or charging nothing changes compared to before. This is **read-only**: no
  command is ever sent to the car and it doesn't drain the battery. It works with the "Automatic
  update" switch turned on (as it already was).

## v1.5.21 — 2026-06-23

### 🇮🇹 Italiano

- **Risolto: non si riusciva più ad aggiungere l'integrazione (errore "not_implemented").**
  Chi installava l'integrazione da zero, alla voce **Aggiungi integrazione → Omoda 9 / Jaecoo**,
  riceveva subito un errore "not_implemented" e non riusciva a inserire email e PIN. La schermata
  di accesso non veniva proposta per niente. Ora la procedura di configurazione (email → codice
  ricevuto via mail → eventuale scelta dell'auto) funziona di nuovo correttamente. Chi aveva già
  configurato l'integrazione in precedenza non era interessato dal problema.

### 🇬🇧 English

- **Fixed: the integration could no longer be added (error "not_implemented").**
  Anyone installing the integration from scratch, under **Add integration → Omoda 9 / Jaecoo**,
  immediately got a "not_implemented" error and couldn't enter their email and PIN. The login
  screen wasn't shown at all. The setup process (email → code received by mail → optional vehicle
  selection) now works correctly again. Anyone who had already configured the integration was not
  affected by this problem.

## v1.5.20 — 2026-06-23

- **Nomi delle entità in italiano o inglese, in automatico secondo la lingua di Home
  Assistant.** Finora i nomi delle entità (Batteria, Autonomia, Porte…) erano sempre in
  italiano. Ora ogni entità è **tradotta**: chi usa Home Assistant in inglese vede "Battery",
  "Total range", "Front left door"…, chi lo usa in italiano vede "Batteria", "Autonomia
  totale", "Porta anteriore SX". Il nome del veicolo fa da prefisso (es. **"Omoda 9 Battery"**,
  o **"Jaecoo 7 Battery"** per chi ha un Jaecoo). `entity_id`, storico, automazioni e dashboard
  **non cambiano**. (Se avevi rinominato a mano qualche entità, il tuo nome personalizzato
  resta e ha la precedenza.)

## v1.5.19 — 2026-06-23

- **Il dispositivo prende il nome reale della tua auto (Omoda 9, Jaecoo 7…).** Prima il
  dispositivo si chiamava sempre "Omoda 9", anche per chi ha un Jaecoo. Ora il nome (e
  marca/modello) vengono **rilevati automaticamente dall'auto** — è lo stesso nome che vedi
  nell'app. Se preferisci, puoi cambiarlo a mano in **Impostazioni → Dispositivi e servizi →
  Omoda 9 / Jaecoo → Configura → "Nome veicolo"**. Gli `entity_id`, lo storico, le automazioni
  e le dashboard **non cambiano** (il dispositivo è identificato dal numero di telaio).

## v1.5.18 — 2026-06-23

- **Il sensore "Connessa" si chiama ora "Connessione".** È sempre lo stesso sensore (uno
  solo, con stato **Connesso/Disconnesso**): il nome neutro si legge meglio quando l'auto
  è offline. Niente di tecnico cambia e i riferimenti esistenti restano validi.

## v1.5.17 — 2026-06-23

- **"Autonomia totale" corretta + nuovo dato "Autonomia benzina".** Il valore che
  l'integrazione chiamava "Autonomia totale" (215 km) in realtà era **solo l'autonomia
  a benzina**, non la somma con l'elettrico: lo si è verificato perché restava fermo a
  215 km mentre l'autonomia elettrica calava (e il serbatoio era invariato). Ora:
  **"Autonomia benzina"** mostra i km col solo motore termico, e **"Autonomia totale"**
  mostra il valore corretto = **elettrico + benzina** (es. 27 + 215 = 242 km).
- **Pressione gomme in bar (come nell'app).** Le quattro pressioni degli pneumatici ora
  sono mostrate in **bar** invece che in kPa (es. 2,79 bar invece di 279 kPa), così
  coincidono con quanto vedi nell'app dell'auto. Potresti vedere una notifica una-tantum
  di "unità cambiata": si risolve da sola, lo storico viene convertito automaticamente.

## v1.5.16 — 2026-06-23

- **L'aggiornamento automatico della ricarica ora parte subito anche dopo un riavvio
  di Home Assistant.** Nella versione precedente, se riavviavi Home Assistant mentre
  l'auto era già in carica, il monitoraggio in tempo reale poteva non avviarsi da solo
  finché non scattava il controllo periodico (anche mezz'ora dopo) — perché l'auto, da
  ferma, non "annuncia" nulla. Ora, **pochi secondi dopo l'avvio**, l'integrazione fa
  una lettura: se trova l'auto in carica (o in marcia) **fa partire immediatamente**
  l'aggiornamento ogni paio di minuti. Sempre in sola lettura, nessun comando all'auto.

## v1.5.15 — 2026-06-23

- **Piccola regolazione del controllo periodico durante la ricarica (ogni 30 minuti
  invece di 39).** È solo una rete di sicurezza: a seguire la carica in tempo reale
  ci pensa già l'aggiornamento automatico ogni paio di minuti introdotto qui sopra.
  Nessun cambiamento visibile nell'uso di tutti i giorni.

## v1.5.14 — 2026-06-23

- **La carica si segue da sola: mentre l'auto è attaccata alla colonnina, batteria,
  tempo che manca alla fine e potenza di ricarica si aggiornano automaticamente.**
  Prima, anche durante la ricarica i dati potevano restare "fermi" all'ultimo valore
  per ore (l'auto non li manda da sola): bisognava premere "Aggiorna stato completo"
  per vederli. Ora, **appena colleghi il cavo, l'integrazione inizia a rileggere i
  dati di carica ogni paio di minuti** e li tiene aggiornati per tutta la durata della
  ricarica — vedi la percentuale che sale e il tempo residuo che scende senza fare
  nulla. Quando stacchi il cavo, smette da sola. Tutto in sola lettura: **nessun
  comando viene inviato all'auto** (durante la carica i dati veri sono già disponibili).

## v1.5.13 — 2026-06-23

- **I chilometri e la batteria ora si aggiornano da soli quando guidi.** Era
  emerso che l'odometro restava "fermo" all'ultimo valore e la batteria sembrava
  bloccata. Il motivo: l'auto comunica i dati **veri** (chilometri totali, carica
  della batteria, tensione) **solo quando l'alta tensione è accesa** — cioè mentre
  la guidi o la ricarichi. A macchina parcheggiata e spenta non c'è nessun dato
  nuovo da leggere (vale anche per l'app ufficiale). Ora, **appena l'auto si
  accende o va in carica, l'integrazione legge i dati freschi più volte di
  seguito**, così i chilometri salgono e la batteria si aggiorna **automaticamente
  durante e dopo ogni viaggio**, senza che tu debba fare nulla.
- **Nuovo pulsante "Aggiorna stato completo".** Se vuoi vedere subito i
  chilometri e la batteria aggiornati mentre l'auto è parcheggiata, premilo:
  accende il **clima per circa un minuto** (è l'unico modo per "risvegliare"
  l'alta tensione), legge i dati reali e poi **rispegne il clima da solo**. Da
  usare solo quando ti serve il dato fresco al volo: nell'uso normale non serve,
  perché ora si aggiorna da sé quando guidi.
- **Niente più "batteria 0%" fuorviante.** Se l'integrazione non ha ancora mai
  letto una carica reale, mostra **"sconosciuto"** invece di un falso 0% — finché
  non arriva il primo dato vero (al primo viaggio/ricarica o col pulsante qui
  sopra).

## v1.5.12 — 2026-06-22

- **La batteria non va più a 0 quando l'auto è parcheggiata.** Quando l'auto è
  ferma e spenta non comunica la carica reale della batteria (manda uno "zero"
  segnaposto): prima questo faceva apparire la **batteria allo 0%** e la
  **tensione/corrente** dell'alta tensione azzerate. Ora l'integrazione riconosce
  questi valori finti e **mantiene l'ultimo valore reale** — esattamente come fa
  l'app ufficiale, che mostra sempre l'ultima carica nota. I valori "veri" di
  batteria, tensione, corrente e consumo elettrico tornano ad aggiornarsi da soli
  quando l'auto è **in marcia o in ricarica** (gli unici momenti in cui l'auto li
  trasmette davvero).

## v1.5.11 — 2026-06-22

- **Login e avvio più robusti.** Migliorata la stabilità in alcune situazioni
  poco comuni: se il server dell'auto risponde in modo inatteso durante l'invio
  del codice OTP o la verifica del captcha, ora l'integrazione **riprova invece
  di bloccarsi**. All'avvio, se qualcosa va storto, **non lascia più processi o
  controlli automatici "appesi"** in sottofondo, e durante lo spegnimento fa
  pulizia in modo più ordinato. Il file con le credenziali dell'auto viene salvato
  in modo **a prova di interruzione** (non può più corrompersi se Home Assistant
  si chiude proprio in quel momento). Infine, quando spegni l'interruttore
  **"Aggiornamento automatico"**, l'aggiornamento periodico si ferma **davvero**,
  senza più riattivarsi da solo. Sono tutti miglioramenti "dietro le quinte": l'uso
  di tutti i giorni non cambia.

## v1.5.10 — 2026-06-22

- **Più facile chiedere aiuto se qualcosa non va.** Aggiunto il pulsante **"Scarica
  diagnostica"** nella pagina dell'integrazione (menù ⋮): con un clic scarichi un file da
  inviare per farti aiutare, **già reso anonimo** — la tua email, il PIN, il numero di
  telaio e soprattutto la **posizione dell'auto** sono nascosti automaticamente, e di
  password e certificati non viene mai mostrato il contenuto. Nel manuale (README) trovi ora
  una sezione **"Risoluzione problemi"** che spiega in parole semplici dove trovare i log e
  come inviarli in sicurezza.

## v1.5.9 — 2026-06-22

- **"Raffredda tutto" e "Riscalda tutto" ora si spengono davvero del tutto (sedili
  posteriori inclusi).** Per spegnere tutto usa lo stesso pulsante **"Raffredda tutto"**
  (o "Riscalda tutto") e mettilo su **OFF**: così spegni aria + **tutti** i sedili, anche
  quelli posteriori. ⚠️ Attenzione: il pulsante **"Clima"** spegne solo l'aria condizionata
  (e, sull'auto, i sedili anteriori che le sono collegati), ma **non** i sedili posteriori —
  quelli sono indipendenti. Inoltre l'interruttore ora **resta acceso** mentre il preset è
  attivo (prima si rispegneva subito e non riuscivi a comandarne lo spegnimento), e **si
  spegne da solo** dopo circa 15 minuti, quando l'auto chiude il preset. Anche lo spegnimento
  sveglia l'auto da solo, così arriva fino ai sedili posteriori.

## v1.5.8 — 2026-06-22

- **"Raffredda tutto" e "Riscalda tutto": basta un tocco, anche con l'auto parcheggiata.**
  I sedili, il volante e gli sbrinatori l'auto li accende solo quando è **sveglia**: se la
  premevi a vettura ferma da un po', l'auto era "addormentata" e rispondeva con un errore.
  Ora la macro **sveglia l'auto da sola e aspetta qualche secondo** prima di mandare il
  comando, quindi ti basta premere una volta e funziona (ci mette ~40 secondi a partire:
  è normale, sta svegliando l'auto). Inoltre il pulsante ora fa **sempre l'accensione**
  quando lo premi: prima, se era rimasto "acceso", il tocco mandava per sbaglio lo
  spegnimento (che dava errore). 💡 Per il momento miglior risultato, usalo con l'**auto
  spenta**.

## v1.5.7 — 2026-06-22

- **"Raffredda tutto" e "Riscalda tutto" ora accendono DAVVERO tutto** (e si corregge
  quanto detto nelle due note precedenti). Le macro tornano a fare ciò che ti aspetti, con
  un unico comando come l'app ufficiale:
  - **❄️ Raffredda tutto** = aria condizionata al massimo freddo **+ ventilazione di tutti
    e quattro i sedili**.
  - **🔥 Riscalda tutto** = aria calda al massimo **+ riscaldamento di tutti e quattro i
    sedili + volante riscaldato + sbrinatore parabrezza + sbrinatore lunotto**.

  Perché prima sembravano "non disponibili": i comandi del comfort (sedili, volante,
  sbrinatori) l'auto li accetta **solo a vettura spenta e con il clima acceso**. Se l'auto
  è accesa/occupata, o se si prova ad accendere un sedile col clima spento, l'auto li
  rifiuta con un errore — e questo mi aveva tratto in inganno facendomi credere, a torto,
  che certi comfort non fossero installati. Verificato dal vivo a motore spento: clima,
  tutti i sedili, volante, parabrezza e lunotto rispondono correttamente. **Consiglio
  d'uso:** lancia "Raffredda/Riscalda tutto" con l'**auto spenta**.

## v1.5.6 — 2026-06-21

- **"Raffredda tutto" e "Riscalda tutto" ora sono vere macro su misura per la tua auto.**
  Abbiamo provato sul campo, uno per uno, tutti i comfort dell'auto per vedere quali
  rispondono davvero ai comandi a distanza. Su questa vettura risultano installati (e
  funzionanti) soltanto il **sedile guidatore ventilato** e lo **sbrinatore del lunotto**;
  riscaldamento dei sedili, volante riscaldato, sbrinatore del parabrezza e ventilazione
  dei sedili passeggero/posteriori **non sono presenti** e andavano solo in errore. Quindi
  adesso:
  - **❄️ Raffredda tutto** = aria condizionata al massimo freddo **+ ventilazione del
    sedile guidatore**.
  - **🔥 Riscalda tutto** = aria calda al massimo **+ sbrinatore del lunotto**.

  I comandi vengono inviati **in sequenza, uno alla volta** (l'auto ne esegue uno per
  volta), quindi la macro impiega qualche secondo in più a completarsi ma non si "accavalla"
  e non genera più gli errori che vedevi. Niente più tentativi sui comfort che la tua auto
  non ha.

## v1.5.5 — 2026-06-21

- **"Raffredda tutto" e "Riscalda tutto" ora funzionano davvero.** Prima questi due
  pulsanti usavano un comando "tutto-in-uno" che la tua auto non riesce a eseguire: dava un
  finto "comando inviato" e subito dopo un errore, e il clima non partiva. Ora usano il
  comando del climatizzatore semplice (lo stesso, affidabile, del termostato "Clima"):
  **"Raffredda tutto"** accende l'aria al massimo freddo, **"Riscalda tutto"** al massimo
  caldo (e accende anche gli sbrinatori di parabrezza e lunotto). Il riscaldamento/la
  ventilazione dei **sedili** non fanno più parte di questi due pulsanti — l'auto non li
  accettava in quel comando — ma restano comandabili dai loro interruttori dedicati.

## v1.5.4 — 2026-06-21

- **Niente più comandi accavallati se premi troppe volte.** L'auto esegue **un comando
  alla volta**: ora, finché un comando è in corso, le pressioni successive vengono
  ignorate con un avviso ("attendi qualche secondo, un comando è già in corso") invece di
  accavallarsi e farsi rifiutare dall'auto come "occupato". Appena l'auto conferma, il
  comando successivo riparte subito. Vale per tutti i comandi che **agiscono** sull'auto
  (clima, serrature, baule/finestrini/tetto, ricarica, sedili, antifurto, "Raffredda/
  Riscalda tutto").

## v1.5.3 — 2026-06-21

- **L'aggiornamento automatico ora parte SPENTO.** Per non svegliare l'auto senza che tu
  lo voglia, la funzione "Aggiornamento automatico" è **disattivata di default**: quando la
  vuoi, accendi tu l'interruttore **"Aggiornamento automatico"** (e regoli gli intervalli
  dalle opzioni). Resta valido il pulsante "Aggiorna posizione" per un aggiornamento manuale.

## v1.5.2 — 2026-06-21

- **Aggiornamento automatico dei dati dell'auto.** Ora Home Assistant aggiorna **da solo**,
  a intervalli regolari, le informazioni dell'auto (posizione, batteria, autonomia, gomme,
  consumi…) svegliando brevemente la vettura. Di **default ogni 60 minuti**, e **ogni 39
  minuti quando l'auto è attaccata alla colonnina** (così segui meglio la ricarica).
  - Puoi cambiare i due intervalli — o disattivarli mettendo **0** — dalle opzioni
    dell'integrazione: **Impostazioni → Dispositivi e servizi → Omoda 9 → Configura**.
  - C'è anche un nuovo interruttore **"Aggiornamento automatico"** per accendere o spegnere
    tutto con un tocco, senza entrare nelle opzioni.
  - ⚠️ Quando è attivo l'auto viene svegliata periodicamente: comodo per avere dati sempre
    freschi, ma comporta un piccolo consumo della batteria a vettura ferma. Se preferisci,
    spegnilo e aggiorna a mano col pulsante "Aggiorna posizione".

- **Stati della ricarica più chiari.** Le informazioni "Stato ricarica", "Presa ricarica
  rapida" e "Ricarica programmata" ora mostrano un **testo leggibile** (es. "Non in ricarica",
  "In ricarica", "Collegata") invece di un codice numerico.

## v1.5.1 — 2026-06-21

- **Correzione: le nuove informazioni dall'auto ora compaiono davvero.** Per un problema
  tecnico, i dati che l'auto comunica quando è sveglia — autonomia, chilometri, pressione e
  temperatura delle gomme, consumi, carburante, tensione della batteria, e perfino **livello
  batteria e velocità** — non venivano letti e restavano vuoti. Ora vengono letti
  correttamente: i relativi sensori si popolano non appena l'auto si sveglia.

- **Avviso quando un comando all'auto non riesce (opzionale).** Ora è disponibile un
  "blueprint" pronto all'uso: se lo importi, ricevi un **popup in Home Assistant** (e, se
  vuoi, una notifica sul telefono) ogni volta che un comando all'auto non va a buon fine —
  ad esempio quando l'auto è occupata da un altro comando, non è raggiungibile, o la
  sessione è scaduta. Riconosce solo i veri errori, quindi non disturba quando va tutto
  bene. L'integrazione di suo continua a **non inviare nessuna notifica**: il blueprint è
  del tutto facoltativo e si attiva con un clic dal README.

## v1.5.0 — 2026-06-21

- **Tante nuove informazioni che arrivano direttamente dall'auto.** Quando l'auto è
  sveglia, Home Assistant ora mostra molti più dati utili, finora non disponibili:
  - **Autonomia**: quanti chilometri restano in elettrico e in totale (elettrico + benzina).
  - **Chilometri totali** dell'auto (contachilometri) e chilometri percorsi in ibrido.
  - **Gomme**: pressione e temperatura di ognuna delle quattro ruote, con un **avviso**
    dedicato per ciascuna gomma se qualcosa non va.
  - **Consumi medi**, sia di benzina sia di energia elettrica.
  - **Carburante rimasto** nel serbatoio (in litri).
  - **Batteria di trazione**: tensione e corrente (informazioni tecniche).
  - **Clima**: la temperatura impostata sui due lati dell'abitacolo.
  - **Ricarica**: stato della presa, stato della ricarica programmata e, quando l'auto è
    in carica, il tempo che manca al termine.
  - **Avviso "batteria scarica"** quando il livello è basso.

  Sono tutte informazioni di **sola lettura** (l'auto non riceve nessun comando) e si
  aggiornano quando l'auto si sveglia. Le trovi sotto il dispositivo "Omoda 9": quelle
  più tecniche (temperature gomme, tensione batteria, ecc.) sono raggruppate tra i
  "dettagli diagnostici".

## v1.4.0 — 2026-06-21

- **Nuovo interruttore "Antifurto".** Puoi accendere e spegnere l'allarme antifurto
  dell'auto direttamente da Home Assistant. Quando è acceso, l'auto fa scattare l'allarme
  e ti avvisa in caso di movimento non autorizzato del veicolo, tentativi di scasso delle
  porte, rottura dei finestrini o altre potenziali effrazioni. L'interruttore mostra anche
  se l'antifurto è già attivo (lo legge dall'auto).
- **Due nuovi tasti "comfort": Raffredda tutto e Riscalda tutto.** Con un solo
  interruttore prepari l'abitacolo per la stagione. **"Raffredda tutto"** accende il
  clima al massimo del freddo e avvia la **ventilazione di tutti i sedili**.
  **"Riscalda tutto"** accende il clima al massimo del caldo e attiva insieme lo
  **sbrinamento di parabrezza e lunotto, il volante riscaldato e il riscaldamento di
  tutti i sedili**. I due tasti si escludono a vicenda: accendendone uno, l'altro si
  spegne. Comodi per scaldare o rinfrescare l'auto in un colpo solo prima di partire.
- **Ricarica programmata: ora scegli l'orario al minuto.** L'ora di inizio della
  ricarica programmata era un cursore a sole ore intere (es. solo "le 8"); adesso c'è un
  vero **selettore d'orario** "Ricarica · orario di inizio" con cui imposti anche i minuti
  (es. **07:45**). La durata resta il cursore in ore. ⚠️ Dopo l'aggiornamento il vecchio
  cursore "Ricarica · ora di inizio" resterà "non disponibile" e si può togliere: al suo
  posto usa il nuovo selettore d'orario.

## v1.3.0 — 2026-06-21

- **Il clima ora si imposta alla temperatura che vuoi.** Prima c'era un semplice
  interruttore che accendeva il clima fisso a 21°; ora trovi un vero **termostato**:
  scegli la temperatura desiderata (da 16° a 30°) e l'auto la applica, riscaldando o
  raffreddando l'abitacolo. Puoi anche regolare per quanti minuti deve restare acceso.
  ⚠️ Dopo l'aggiornamento, al posto del vecchio interruttore "Clima" comparirà il nuovo
  termostato "Clima": se avevi messo il vecchio interruttore in una schermata, sostituiscilo
  con il nuovo (il vecchio resterà "non disponibile" e si può togliere).
- **Comandi per la ricarica elettrica.** Due nuovi interruttori: **"Ricarica"** per
  avviare o fermare subito la ricarica, e **"Ricarica programmata"** per far caricare
  l'auto in una fascia oraria scelta (imposti ora di inizio e durata con i due cursori
  dedicati). Funzionano quando l'auto è collegata alla colonnina/wallbox.
- **I sedili e gli sbrinamenti non si toccano più accendendo il clima.** Il nuovo
  termostato agisce solo sull'aria: riscaldamento sedili, volante e sbrinamenti restano
  controlli a parte e non vengono spenti quando accendi o spegni il clima.

## v1.2.0 — 2026-06-21

- **Comandi anche per i sedili passeggero e posteriori.** Finora potevi accendere e
  spegnere solo il sedile del posto guida; ora trovi gli stessi interruttori (caldo e
  aria) anche per il **passeggero** e per i due **sedili posteriori** (sinistro e
  destro). Come per il guida, su ogni sedile caldo e aria si escludono a vicenda.
- **Nuove informazioni dall'auto.** Compaiono tre nuove indicazioni quando l'auto è
  sveglia: se la **spina di ricarica è collegata**, se il **motore è acceso**, e lo
  stato di movimento del **tetto apribile** (quest'ultimo tra i dettagli tecnici).
- **L'esito dei comandi ora arriva davvero dall'auto.** Prima la voce "Esito comando"
  diceva solo che il comando era stato *accettato* dal server; adesso, quando l'auto
  risponde, viene aggiornata con l'esito **reale**: comando eseguito e confermato,
  ancora in corso, oppure non riuscito (con il motivo segnalato dall'auto).

- **Riscaldamenti e sbrinamenti ora si spengono con un tocco.** Sbrinamento
  parabrezza, sbrinamento lunotto, volante riscaldato e i sedili (caldo/aria) del
  posto guida diventano dei normali interruttori: prima potevi solo accenderli (e si
  spegnevano da soli dopo 15 minuti), ora li accendi **e li spegni** quando vuoi,
  vedendo lo stato acceso/spento nella stessa card.
- **Sedile guida più furbo.** Caldo e aria del sedile guida non possono stare accesi
  insieme: accendendo l'aria il riscaldamento si spegne (e viceversa), proprio come
  fa l'auto — e ora la card lo mostra subito.
- **Tasto "Sveglia auto" più affidabile.** Se la sveglia via SMS non risponde
  (capitava che l'auto restasse a riposo), l'integrazione prova in automatico a
  contattare l'auto con la richiesta di posizione, che la sveglia al primo colpo e
  in più aggiorna la posizione GPS.
- **Schermata più pulita.** Un paio di indicazioni che l'auto non comunica mai da
  ferma (tendina del tetto, riscaldamento parabrezza) sono state spostate tra i
  dettagli diagnostici, così non restano "in dubbio" tra i controlli principali.

## v1.0.0 — 2026-06-21

- **Versione 1.0: l'integrazione diventa stabile e più affidabile.** Tante piccole
  rifiniture sotto il cofano per un funzionamento più solido di tutti i giorni.
- **Connessione all'auto più robusta.** Se il collegamento cade viene ristabilito
  da solo, senza lasciare l'integrazione "appesa"; meno disconnessioni inattese e
  un avvio più pulito quando l'auto non è raggiungibile.
- **Accesso più sicuro e protetto.** Migliorata la gestione dell'accesso per evitare
  che la sessione si perda da sola; aggiunta una protezione che ferma i tentativi se
  il PIN risulta sbagliato, così l'account non rischia il blocco.
- **Informazioni sempre veritiere dopo un riavvio.** Dopo aver riavviato Home
  Assistant, gli esiti dei comandi non mostrano più un risultato vecchio: o è
  aggiornato o resta vuoto, niente informazioni fuorvianti.
- **Stati più coerenti.** Porte, serratura, baule, finestrini, tetto e clima
  vengono interpretati in modo uniforme: niente più "acceso" o "aperto" mostrati
  per sbaglio quando il dato non c'è.
- **Comandi con conferma a schermo.** Quando premi un comando (chiudi/apri/clima)
  la card si aggiorna subito e, se qualcosa non va a buon fine, te lo segnala invece
  di restare bloccata su uno stato mai raggiunto.
- **Pronta anche fuori dall'Europa.** In fase di configurazione si può ora indicare
  il server dell'auto della propria zona, così l'integrazione funziona anche fuori
  dalla regione europea.
- **La posizione GPS resta salvata.** L'ultima posizione nota viene conservata e
  ricompare dopo un riavvio, invece di sparire.

## v0.3.0 — 2026-06-21

- **La serratura ora è un vero lucchetto.** La blocchi e la sblocchi con un solo
  tocco, e vedi lo stato (chiusa/aperta) nella stessa card. Prima erano
  un'indicazione separata e due pulsanti distinti.
- **Il clima ora è un interruttore.** Lo accendi e lo spegni come una normale luce
  (l'accensione avvia la climatizzazione a 21° per 15 minuti).
- **Baule, finestrini e tetto si comandano come tapparelle.** Apri e chiudi
  direttamente, con stato e comando insieme. (La ventilazione finestrini resta un
  pulsante a parte.)
- **Schermata principale più pulita.** Le informazioni di servizio — esiti dei
  comandi, orari dell'ultimo contatto, stato della sessione e campo del codice OTP —
  sono state spostate nella sezione "diagnostica" del dispositivo, così in primo
  piano restano solo i controlli che usi davvero.
- **Andamenti nel tempo per batteria e velocità.** Ora vengono registrate
  storicamente: puoi vederne i grafici e usarle nelle statistiche.

## v0.2.6 — 2026-06-21

- Aggiunto questo elenco delle novità (changelog), così a ogni aggiornamento
  vedi in chiaro cosa è cambiato.
- README più chiaro: per iniziare bastano **email + PIN** del tuo account
  (più un **codice OTP** via email al primo accesso). Tutto il resto è automatico.

## v0.2.4 — 21 giugno 2026

- **Certificati automatici.** Non devi più procurarti o inserire alcun
  certificato: l'integrazione li installa da sola in base alla tua regione.
  L'attivazione richiede ora soltanto email e PIN.

## v0.2.1 — 21 giugno 2026

- **Accesso più semplice.** Ora puoi accedere direttamente da Home Assistant
  inserendo email e PIN e confermando il codice OTP ricevuto via email, senza
  strumenti esterni e su qualunque installazione (anche Home Assistant OS).

## Versioni precedenti

- Prime versioni dell'integrazione: collegamento dell'auto a Home Assistant
  (stato porte/serrature/baule/cofano/finestrini/tetto/clima/sedili), posizione
  GPS su richiesta, batteria e velocità ad auto in marcia, pulsanti dei comandi.
