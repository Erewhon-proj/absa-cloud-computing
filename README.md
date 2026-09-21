# ABSA Cloud

Progetto per il corso di Cloud Computing: una piattaforma a microservizi per la
**Aspect-Based Sentiment Analysis** di recensioni bancarie in italiano.
L'utente invia una recensione, il sistema la mette in coda e un worker ne estrae
gli aspetti (app, costi, assistenza, ...) con il relativo sentiment.

```
[Streamlit] --HTTP--> [API FastAPI] --> [RabbitMQ] --> [Worker] --> [PostgreSQL]
 frontend               gateway           coda         inferenza       dati
```

L'API risponde subito con `202 Accepted` e il worker elabora le recensioni con
calma, a batch. In Kubernetes il numero di worker lo decide KEDA in base a quanti
messaggi ci sono in coda (da 0 a 5).

## Struttura

```
services/          api, worker e frontend (un Dockerfile ciascuno)
db/                schema del database
models/            qui va scaricato il checkpoint del modello (non è su git)
k8s/local/         manifest Kubernetes per il cluster locale
k8s/local-pyabsa/  modifiche al worker per usare il modello reale in locale
k8s/aws/           manifest per EKS
terraform/         local/ per il namespace, aws/ per la parte cloud
ansible/           playbook che fanno build e deploy
scripts/           load test e script di supporto
tests/             test con pytest
docs/              relazione e schemi dell'architettura
```

Il worker ha due modalità, scelte con `MODEL_MODE`:

- `mock` (default): un'euristica a parole chiave. Non serve il modello e parte in
  pochi secondi, va bene per provare il progetto.
- `pyabsa`: il modello vero (LCF-ATEPC su BERT italiano). Il checkpoint pesa
  circa 450 MB e **non è nel repository**, vedi [Modello reale](#modello-reale).

In locale si può avviare in quattro modi:

| | Mock | Modello reale |
|---|---|---|
| **Docker Compose** | `docker compose up --build` | `docker compose -f docker-compose.yml -f docker-compose.pyabsa.yml up --build` |
| **Kubernetes + KEDA** | `ansible-playbook ansible/local/playbook.yml` | `ansible-playbook ansible/local/playbook.yml -e model_mode=pyabsa` |

Compose è il modo più semplice, Kubernetes è quello che mostra l'autoscaling.
Per il modello reale prima va scaricato il checkpoint (vedi
[Modello reale](#modello-reale)).

La versione cloud è descritta in [Deploy su AWS](#deploy-su-aws).

## Opzione 1: Docker Compose

Serve solo Docker (OrbStack, Docker Desktop o Docker Engine su Linux).

```bash
docker compose up --build
```

- Frontend: http://localhost:8501
- API (documentazione Swagger): http://localhost:8000/docs
- RabbitMQ: http://localhost:15672 (guest / guest)

Per avere più worker:

```bash
docker compose up --build --scale worker=3 -d
```

Per spegnere tutto (`-v` cancella anche i dati del database):

```bash
docker compose down -v
```

### Con il modello reale

Dopo aver messo il checkpoint in `models/` (vedi [Modello reale](#modello-reale)):

```bash
docker compose -f docker-compose.yml -f docker-compose.pyabsa.yml up --build
```

`docker-compose.pyabsa.yml` cambia solo il worker: lo builda con PyABSA, lo
imposta su `MODEL_MODE=pyabsa` e gli monta la cartella del modello. Il percorso
è relativo alla cartella del progetto, quindi non va modificato. Per spegnere
si usano gli stessi due `-f`:

```bash
docker compose -f docker-compose.yml -f docker-compose.pyabsa.yml down -v
```

## Opzione 2: Kubernetes + KEDA

### Requisiti

- un cluster Kubernetes locale, vedi sotto
- `terraform`, `ansible` e `kubectl`
- connessione a internet (il playbook installa KEDA dal suo manifest ufficiale)

Il progetto è stato sviluppato su **OrbStack**, ma va bene anche **Docker Desktop**.
Per tutti e due vale una cosa importante: le immagini buildate con `docker build`
sono subito visibili al cluster, quindi non serve un registry.

| | OrbStack (macOS) | Docker Desktop (macOS, Windows, Linux) |
|---|---|---|
| Attivare Kubernetes | Settings → Kubernetes | Settings → Kubernetes, modalità *kubeadm* |
| Nome del contesto | `orbstack` | `docker-desktop` |
| `kubectl` | incluso | incluso |

Su Windows il playbook va lanciato da **WSL2**, perché Ansible non gira
direttamente su Windows.

### Deploy

Dalla cartella del progetto:

```bash
# OrbStack
ansible-playbook ansible/local/playbook.yml

# Docker Desktop
ansible-playbook ansible/local/playbook.yml -e kube_context=docker-desktop
```

Il playbook in ordine:

1. crea il namespace `absa-cloud` con Terraform;
2. builda le tre immagini;
3. installa KEDA;
4. applica i manifest in `k8s/local/`;
5. riavvia i deployment la cui immagine è cambiata;
6. aspetta che i pod siano pronti.

La prima volta ci mette qualche minuto per la build, dopo meno di un minuto.
Dopo una modifica al codice basta rilanciare il playbook: il punto 5 serve
perché il tag è sempre `:latest` e, senza riavvio, i pod resterebbero con il
codice vecchio.

Tutti i comandi usano il contesto indicato in `kube_context`, non quello attivo
in quel momento: se il `kubectl` è ancora puntato su un altro cluster, il
playbook non ci installa niente.

Gli indirizzi sono gli stessi di Compose (8501, 8000, 15672).

```bash
kubectl --context orbstack -n absa-cloud get pods
```

Il worker all'inizio è a **0 repliche**: è normale, KEDA lo avvia quando arrivano
messaggi in coda.

### Con il modello reale

Dopo aver messo il checkpoint in `models/` (vedi [Modello reale](#modello-reale)):

```bash
ansible-playbook ansible/local/playbook.yml -e model_mode=pyabsa
```

Rispetto al deploy normale il playbook:

- controlla che il checkpoint ci sia, e se manca si ferma subito;
- builda il worker con PyABSA e PyTorch;
- applica `k8s/local-pyabsa/`, che riusa i manifest di `k8s/local/` e cambia
  solo il worker: più memoria e CPU, massimo 1 replica e la cartella del modello
  montata con `hostPath`.

Il percorso assoluto del modello, che `hostPath` richiede, lo calcola il playbook
dalla cartella del progetto. Se il checkpoint sta altrove si indica così:

```bash
ansible-playbook ansible/local/playbook.yml -e model_mode=pyabsa -e model_dir=/percorso/del/checkpoint
```

Il worker è limitato a **1 replica** perché ognuno tiene il modello in memoria
(circa 2 GB mentre lo carica): con 4 GB assegnati a Docker, due worker insieme
esauriscono la memoria del cluster. Con più RAM si può alzare `maxReplicaCount`
in `k8s/local-pyabsa/worker.yaml`.

È stato provato su OrbStack, che rende visibili al cluster le cartelle del Mac.
Se in un altro ambiente il cluster vede i file con un percorso diverso, basta
passare quello con `-e model_dir=...`.

Per tornare al mock basta rilanciare il playbook senza `-e model_mode=pyabsa`.

### Altri cluster (k3d, minikube, kind)

Funzionano, ma richiedono dei passi in più che il playbook non fa:

- **caricare le immagini nel cluster** dopo la build, perché questi cluster non
  vedono le immagini di Docker (`k3d image import`, `minikube image load`,
  `kind load docker-image`);
- **esporre i Service** `LoadBalancer` sulle porte 8000 e 8501 (per esempio
  `minikube tunnel`, oppure l'opzione `-p` in `k3d cluster create`);
- solo per il modello reale, **rendere visibile la cartella `models/`** dentro il
  nodo (`minikube mount`, `--volume` in `k3d cluster create`, `extraMounts` in
  kind) e passare quel percorso con `-e model_dir=...`.

### Vedere l'autoscaling

In locale il mock aspetta 2 secondi per ogni batch (`MOCK_DELAY` in
`k8s/local/01-config.yaml`). Altrimenti è così veloce che un worker basterebbe
sempre e KEDA non avrebbe motivo di scalare.

Lo script di load test ha bisogno di `requests`:

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements-dev.txt
```

In un terminale invia le recensioni, in un altro guarda i pod:

```bash
python scripts/load_test.py --url http://localhost:8000 --n 300 --concurrency 30
kubectl --context orbstack -n absa-cloud get pods -l app=worker -w
```

Con 300 recensioni i worker salgono fino a 5 e, svuotata la coda, tornano a 0
dopo circa 30 secondi.

### Spegnere

```bash
terraform -chdir=terraform/local destroy -var kube_context=orbstack
```

Cancellare il namespace elimina anche tutto quello che c'è dentro (pod, database,
coda). KEDA resta installato nel cluster.

## Modello reale

1. Scarica il checkpoint e mettilo in `models/`: link e struttura della
   cartella sono in [models/README.md](models/README.md).
2. Avvia con Compose o con Kubernetes, come descritto sopra.

Cose da sapere prima di provarlo:

- **Memoria:** servono almeno **4 GB assegnati a Docker** (in OrbStack o Docker
  Desktop: Settings → Resources/System). Il worker da solo usa circa 1,2 GB, con
  picchi vicini a 2 GB mentre carica il modello.
- **Spazio:** l'immagine del worker con PyTorch (versione CPU) pesa circa 2,6 GB,
  e la prima build richiede qualche minuto.
- **Internet:** al primo batch PyABSA scarica da Hugging Face alcuni file del
  modello BERT di base e un piccolo modello di spaCy. Il checkpoint addestrato
  invece viene solo letto da `models/`.
- **Tempi:** il primo batch arriva dopo circa un minuto, perché il modello va
  caricato. Poi, su CPU, un batch da 16 recensioni richiede circa un minuto.
- **Se qualcosa va storto:** se PyABSA non riesce a caricare il modello, il worker
  scrive l'errore nei log e usa il mock, così le recensioni non restano bloccate
  in coda. Si riconosce dai risultati: il mock restituisce aspetti generici
  (`costi`, `assistenza`) con `confidence` vuota, il modello reale le parole del
  testo con la loro confidenza. Per controllare:

  ```bash
  docker compose logs worker | grep "PyABSA non disponibile"
  kubectl --context orbstack -n absa-cloud logs -l app=worker | grep "PyABSA non disponibile"
  ```

## Deploy su AWS

In cloud l'architettura resta la stessa, cambiano i servizi: RabbitMQ diventa
**SQS**, PostgreSQL diventa **RDS** e i container girano su **EKS**, dove KEDA
scala il worker in base ai messaggi nella coda SQS. Il codice non cambia: la
coda da usare si sceglie con `QUEUE_BACKEND` (`rabbitmq` oppure `sqs`). Su AWS il
worker usa sempre il modello reale, che scarica da S3 quando parte.

L'infrastruttura è divisa in due stack Terraform:

| Stack | Cosa crea | Quando |
|---|---|---|
| `terraform/aws/persistent` | bucket S3 del modello, repository ECR delle immagini, AWS Budgets, ruolo IAM per la GitHub Action | una volta sola, resta acceso |
| `terraform/aws/compute` | VPC, EKS, RDS, SQS, ruoli IAM dei pod, KEDA | a ogni sessione, poi si distrugge |

Lo stack `persistent` costa pochi centesimi al mese. Lo stack `compute` invece
si paga a ore (control plane EKS, tre nodi `m7i-flex.large` spot, un NAT gateway
e RDS `db.t3.micro`), quindi va distrutto a fine sessione. AWS Budgets manda una
email quando la spesa del mese supera 10, 50 e 100.

### Requisiti

- un account AWS e la AWS CLI configurata (`aws configure`)
- `terraform`, `kubectl`, `ansible`, `python3` e Docker con `buildx`
- la collection Ansible usata per leggere gli output di Terraform:

  ```bash
  ansible-galaxy collection install -r ansible/aws/requirements.yml
  ```

- il checkpoint del modello in `models/` (vedi [models/README.md](models/README.md))

### 1. Stack persistent (una volta sola)

```bash
cp terraform/aws/persistent/terraform.tfvars.example terraform/aws/persistent/terraform.tfvars
# nel file: model_bucket_name (unico su tutto S3), budget_notify_email e github_repo
terraform -chdir=terraform/aws/persistent init
terraform -chdir=terraform/aws/persistent apply
```

### 2. Stack compute

```bash
cp terraform/aws/compute/terraform.tfvars.example terraform/aws/compute/terraform.tfvars
# nel file: model_bucket_name, lo stesso dello stack persistent
export TF_VAR_db_password='...'   # solo lettere, cifre e _ . ~ -, da 8 a 128 caratteri
terraform -chdir=terraform/aws/compute init
terraform -chdir=terraform/aws/compute apply
```

Ci vogliono 15-20 minuti, quasi tutti per creare il cluster EKS. Se il primo
`apply` fallisce mentre installa KEDA perché il cluster non è ancora pronto,
basta rilanciarlo.

### 3. Deploy delle applicazioni

```bash
# primo deploy: carica anche il modello su S3
ansible-playbook ansible/aws/playbook.yml -e upload_model=true

# deploy successivi: il modello è già su S3
ansible-playbook ansible/aws/playbook.yml
```

Il playbook:

1. legge gli output di Terraform (URL della coda, indirizzo del database, ruoli IAM, ...);
2. configura `kubectl` sul cluster EKS;
3. builda le tre immagini per `linux/amd64` e le pubblica su ECR;
4. se richiesto, carica il checkpoint su S3;
5. crea le tabelle su RDS con un Job dentro il cluster, perché il database sta
   in una subnet privata e da fuori non si raggiunge;
6. applica i manifest di `k8s/aws/`, inserendo i valori letti da Terraform;
7. stampa gli indirizzi pubblici di API e frontend.

Su un Mac con chip Apple la build per `amd64` è emulata, e per l'immagine del
worker ci vuole parecchio. Se la GitHub Action ha già pubblicato le immagini, si
può saltare con `-e build_images=false`.

### Provarlo

```bash
kubectl -n absa-cloud get svc api frontend
```

Il frontend risponde sulla porta 80 dell'indirizzo in `EXTERNAL-IP`, l'API sulla
8000. Appena creati, gli indirizzi possono impiegare un paio di minuti a
funzionare.

```bash
API=$(kubectl -n absa-cloud get svc api -o jsonpath='{.status.loadBalancer.ingress[0].hostname}')
python scripts/load_test.py --url "http://$API:8000" --n 300 --concurrency 30
kubectl -n absa-cloud get pods -l app=worker -w
```

I worker salgono fino a 4 e tornano a 0 dopo 5 minuti di coda vuota: su AWS
l'attesa è più lunga perché far ripartire un worker costa molto (immagine da
qualche GB, modello da scaricare e caricare in memoria).

### Spegnere

```bash
./scripts/aws_teardown.sh
```

Lo script prima cancella il namespace, e con lui i LoadBalancer: questi li crea
Kubernetes, non Terraform, e se restano attivi il `destroy` della VPC fallisce.
Poi distrugge lo stack `compute` e controlla che non siano rimasti cluster o
database. Prima di iniziare verifica che `kubectl` punti davvero a EKS, per non
cancellare per sbaglio l'ambiente locale.

S3, ECR e Budgets restano. Per ripartire basta rifare i passi 2 e 3, senza
`upload_model`.

### GitHub Action

A ogni push su `main` la action in `.github/workflows/ci.yml` esegue ruff, i
test, `terraform fmt` e `terraform validate`. Se passano tutti, builda le tre
immagini e le pubblica su ECR.

Per pubblicare su ECR la action non usa chiavi AWS salvate nel repository: si
autentica con OIDC e assume un ruolo IAM che può solo fare push su ECR, e solo
dal branch `main` di questo repository. L'ARN del ruolo va messo nei secret del
repository (Settings → Secrets and variables → Actions) con il nome
`AWS_ECR_PUSH_ROLE_ARN`:

```bash
terraform -chdir=terraform/aws/persistent output -raw github_actions_role_arn
```

Senza il secret i controlli girano lo stesso, fallisce solo la pubblicazione
delle immagini. Il deploy sul cluster resta manuale con Ansible: il cluster
esiste solo durante le sessioni, e un deploy automatico troverebbe quasi sempre
un cluster spento.

## Test e lint

```bash
pip install -r services/worker/requirements.txt -r services/api/requirements.txt -r requirements-dev.txt
ruff check .
pytest tests/
```

Gli stessi controlli, più `terraform fmt` e `terraform validate`, girano nella
GitHub Action a ogni push su `main`.
