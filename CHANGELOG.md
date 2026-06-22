# Novità di Omoda 9 / Jaecoo per Home Assistant

Cosa cambia a ogni aggiornamento, spiegato in parole semplici.
Le voci più recenti sono in alto. Le versioni indicano la "puntata"
dell'integrazione: aggiorna da **HACS → Omoda 9 / Jaecoo → Aggiorna**.

## [Non rilasciato]

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
