# LegalSaathi Logging

This folder contains the local Logstash baseline for LegalSaathi observability.

The app writes structured JSON logs to stdout. When `LOG_FILE_PATH` is set, the
backend also writes the same JSON events to a local JSONL file. Logstash tails
that file and emits normalized events to stdout plus a processed JSONL file.

## Local File Layout

```text
Logs/
  app/                         # generated backend JSONL logs, ignored by git
  processed/                   # generated Logstash output, ignored by git
  logstash/
    config/logstash.yml
    pipeline/logstash.conf
    state/                     # generated sincedb state, ignored by git
```

## Docker Compose

```bash
cd /Users/rajeevbarnwal/Desktop/Codes/LegalSaathi
docker compose up logstash
```

The Logstash monitoring API is exposed on:

```text
http://localhost:1038
```

## Local Backend With File Logging

When running the backend outside Docker, set:

```bash
LOG_FILE_PATH=../Logs/app/backend.jsonl
```

Example:

```bash
cd /Users/rajeevbarnwal/Desktop/Codes/LegalSaathi/backend
source .venv/bin/activate
LOG_FILE_PATH=../Logs/app/backend.jsonl \
BACKEND_PORT=1041 \
CORS_ORIGINS='["http://localhost:1040","http://127.0.0.1:1040"]' \
uvicorn app.main:app --reload --host 0.0.0.0 --port 1041
```

## Scope

This is a local development baseline. It captures backend application/request
logs. Browser-side frontend logs are not centrally collected yet; that should be
handled later via a deliberate telemetry endpoint or OpenTelemetry browser
instrumentation rather than scraping browser consoles.
