FROM python:3.11-slim

WORKDIR /app

# Imposta a "true" per installare le dipendenze ML (modello reale PyABSA).
ARG INSTALL_ML=false

# Installa git perché la libreria PyABSA lo richiede internamente
RUN apt-get update && apt-get install -y git && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY requirements-ml.txt .
RUN if [ "$INSTALL_ML" = "true" ]; then \
        pip install --no-cache-dir -r requirements-ml.txt; \
    fi

COPY app ./app

CMD ["python", "-m", "app.worker"]
