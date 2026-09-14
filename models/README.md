# Modello ABSA

Qui va il checkpoint del modello usato dal worker in modalità `pyabsa`
(LCF-ATEPC addestrato su `dbmdz/bert-base-italian-xxl-cased`).
Pesa circa 450 MB, quindi non è su GitHub: va scaricato a parte.

**Download:** https://drive.google.com/drive/folders/1XZHoWjPV-P0BegFLbPwr6VzGzr28tc-C?usp=drive_link

Dopo aver scaricato ed estratto l'archivio, la cartella deve essere questa:

```
models/
└── lcf_atepc_custom_dataset_cdw_apcacc_89.41_apcf1_69.72_atef1_69.94/
    ├── lcf_atepc.args.txt
    ├── lcf_atepc.config
    ├── lcf_atepc.state_dict
    └── lcf_atepc.tokenizer
```

Il nome della cartella va lasciato così, perché è quello che si aspettano
`docker-compose.pyabsa.yml`, `ansible/local/playbook.yml` e
`ansible/aws/playbook.yml`.

Per avviarlo vedi la sezione *Modello reale* del README principale. Senza il
checkpoint il progetto funziona lo stesso in modalità `mock`.
