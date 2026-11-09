# Deployment

## Local prerequisites

- Python 3.11+
- Node.js 20+
- PostgreSQL 15+ for production-like development

The backend defaults to SQLite for local setup. Set `CUSTOMS_DATABASE_URL` to a PostgreSQL connection string when using PostgreSQL.

## Local installation

```powershell
cd backend
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -e .
uvicorn app.main:app --reload
```

Seed local demo accounts:

```powershell
python -m app.seed_demo
```

Demo accounts use password `password`:

- `executive@example.com`
- `manager@example.com`
- `importer@example.com`

The seed command also creates the client-provided demonstration shipments:

- `SHP-24811` — Company B, LED panel light, with the documented gross-weight discrepancy workflow.
- `SHP-24812` — Company C, invoice-only sample.

The seeded extraction records are labelled `synthetic-demo-data` or client-provided sample information and are not represented as live AI output.

In another terminal:

```powershell
cd frontend
npm install
npm run dev
```

## Environment variables

- `CUSTOMS_DATABASE_URL`
- `CUSTOMS_SECRET_KEY`
- `CUSTOMS_ACCESS_TOKEN_EXPIRE_MINUTES`
- `CUSTOMS_LOCAL_STORAGE_PATH`
- `CUSTOMS_MAX_UPLOAD_SIZE_BYTES`
- `CUSTOMS_MAX_PROCESSING_ATTEMPTS`
- `CUSTOMS_CORS_ORIGINS` (comma-separated frontend origins, for example `http://localhost:5173,http://127.0.0.1:5173`)
- `CUSTOMS_AI_PROVIDER` (`gemini`, `openai`, `anthropic`, `azure-openai`, `ollama`, `vllm`, `lm-studio`, or another OpenAI-compatible provider)
- `CUSTOMS_AI_API_KEY` (provider key; keep it only in `backend\.env` or the deployment secret store)
- `CUSTOMS_AI_MODEL` (provider model name)
- `CUSTOMS_AI_BASE_URL` (required for OpenAI-compatible providers; optional for Gemini and Anthropic)
- `CUSTOMS_AI_TIMEOUT_SECONDS` (defaults to `60`)
- `CUSTOMS_AI_ANTHROPIC_VERSION` (defaults to `2023-06-01`)
- `CUSTOMS_OCR_PROVIDER` (defaults to `paddleocr`)
- `CUSTOMS_OCR_DPI` (defaults to `200`)
- `CUSTOMS_OCR_LANGUAGE` (defaults to `en`)

Secrets must be supplied through the deployment environment and never committed.

## Storage and processing

Development uses a private local storage directory. Production should use private object storage in an explicitly India-region deployment, with signed short-lived downloads and server-side authorization. Document processing initially uses persisted status and retry counters; Redis/Celery will be introduced only when processing latency or deployment requirements justify a worker queue.

## Phase 1 document processing

After uploading a document, staff can start digital-PDF processing:

```text
POST /api/shipments/{shipment_id}/documents/{document_id}/process
```

Text-based PDFs are extracted with PyMuPDF. Scanned PDFs are rendered page-by-page and JPG/PNG files are preprocessed with OpenCV before PaddleOCR recognition. OCR confidence and source coordinates are retained in the extraction run metadata. OCR text is then sent to the configured AI provider, validated against the document-specific Pydantic schema, and persisted with field provenance, line items, and container numbers. If OCR dependencies are not installed, processing fails explicitly with an actionable error and users can use the manual-entry fallback. Missing credentials, provider errors, malformed JSON, and schema-invalid responses are persisted as failed attempts; retries stop at `CUSTOMS_MAX_PROCESSING_ATTEMPTS`.

For local live extraction, install `pip install -e ".[processing]"`, copy `backend\.env.example` to `backend\.env`, select a provider, and set its API key. Never paste the key into chat, frontend code, logs, or source control. Automated tests use mocked provider responses and do not require AI or OCR credentials. Providers that do not expose the same API format require a dedicated adapter; the OpenAI-compatible adapter covers providers exposing `/chat/completions`.

Validation reads the latest successful extraction run for each available document and applies the latest human correction state before evaluating rules. The validation request body can be `{}`; legacy manually supplied values are accepted for compatibility but are not used as the source of truth.

## Approval, export, and accuracy

Executive submission and manager approval require all three filing documents, mandatory fields, reviewed fields, confirmed low-confidence fields, a completed validation run, and only `PASSED` validation results. CSV and XLSX exports repeat these backend checks and record an export log. Install `pip install -e ".[export]"` for XLSX support.

Accuracy reports use explicitly recorded ground-truth labels through the field ground-truth endpoint. They report overall, field-wise, and supplier-wise accuracy, correction counts, and evaluation sample size. Without labels, measured accuracy remains `null`; AI confidence and corrections are never treated as accuracy by themselves.

The automated suite covers provider response normalization and failures, OCR fallback behavior, missing values, discrepancy rules, persisted validation inputs, correction-aware validation data, approval blockers, export row contents, and ground-truth reporting.

## Document review workspace

Authenticated users can preview an uploaded document through:

```text
GET /api/shipments/{shipment_id}/documents/{document_id}/content
```

The endpoint verifies shipment access, resolves the private storage path safely, and returns only supported PDF/JPG/PNG content. The frontend fetches the content with the access token, provides page and zoom controls, and lets reviewers select a field to navigate to its source page. Image source coordinates are highlighted when available; PDF coordinates remain visible as provenance metadata because browser PDF viewers do not expose a reliable overlay surface.
