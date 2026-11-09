# Technical Design Document

## Scope

This system extracts structured customs-document data, validates it deterministically across documents, supports human correction and manager approval, and generates a documented demonstration export. It does not replace customs filing software.

## Revised data design

`users` belongs optionally to an `importer`; `shipments` belongs to an importer and creator; `documents` belongs to a shipment; `document_versions` preserves every uploaded file. The next schema increment adds invoice, packing-list, and bill-of-lading extraction records, line items, containers, field provenance, corrections, validations, approvals, exports, and audit events.

Every field provenance record will retain document ID, page, confidence, immutable original value, optional coordinates, extraction timestamp, and review state. Human corrections reference the original extraction rather than overwriting it.

## Extraction contracts

Separate Pydantic contracts will model invoice, packing list, and bill of lading responses. Each field is represented as present, missing, or unreadable; repeated values use arrays. AI responses are schema-validated before persistence and failed responses remain failed with retry metadata.

Phase 1 uses PyMuPDF for digital PDF text extraction and a provider-neutral AI adapter. Native adapters support Gemini and Anthropic; an OpenAI-compatible adapter supports OpenAI, Azure-compatible gateways, Ollama, vLLM, LM Studio, and other services exposing `/chat/completions`. Every adapter returns JSON that is validated with the corresponding Pydantic contract before persistence. OCR remains an explicit provider boundary; unconfigured OCR fails with an actionable error rather than producing fabricated extraction data. Processing attempts, statuses, and errors are persisted for retry and operational review.

## Validation and workflow

Validation rules are independent deterministic services. They normalize units, apply configurable numeric tolerances and rounding, account for taxes/discounts/additional charges, and refuse currency comparison without a conversion policy. Results are `PASSED`, `FAILED`, `NEEDS_REVIEW`, or `NOT_AVAILABLE`. Corrections identify affected fields and trigger only dependent rules.

Manager approval requires all mandatory fields resolved, mandatory low-confidence fields confirmed, no blocking validation failures, and executive submission. Export repeats these checks in the backend and records an immutable export history.

The review workspace serves private document content only after shipment authorization. It supports PDF/image preview, page navigation, zoom, field-to-source page selection, and coordinate highlighting for image sources where OCR coordinates exist. Human corrections remain separate from the original extraction.

Approval and export repeat the same backend gate: required documents and fields must exist, unresolved or low-confidence fields must be reviewed, validations must exist and pass, and a manager approval must be recorded before export. CSV and optional XLSX exports include shipment, party, invoice, line-item, package, weight, and container data. Accuracy is calculated only from explicit human ground-truth labels, with field-wise and supplier-wise sample sizes.

The test strategy includes mocked AI provider responses and failures, OCR fallback, missing-field handling, cross-document discrepancies, correction-triggered validation state, approval/export restrictions, export contents, and ground-truth accuracy calculations.

## Accuracy

Confidence is model metadata, not accuracy. Accuracy reports use explicitly human-verified ground truth labels, report labelled-field counts and evaluation method, and do not count every correction as a complete evaluation.

## Delivery plan

1. Scaffold, database, migrations, authentication, and shipment management.
2. Complete executive and manager document workflow.
3. Add extraction contracts, provenance, deterministic validation, corrections, approval, and export.
4. Add importer access after the core staff workflow works.
5. Add focused tests and deployment documentation.

This sequence is intentionally sized for a seven-day implementation window.
