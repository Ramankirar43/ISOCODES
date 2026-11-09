import React, { FormEvent, useEffect, useState } from "react";
import { createRoot } from "react-dom/client";
import { BrowserRouter, Link, Navigate, Route, Routes, useNavigate } from "react-router-dom";
import "./styles.css";

const API_URL = import.meta.env.VITE_API_URL ?? "http://127.0.0.1:8000";
type User = { full_name: string; email: string; role: "executive" | "manager" | "importer" };
type Shipment = { id: string; shipment_number: string; importer_id: string; supplier_name: string | null; status: string; created_at: string };
type Importer = { id: string; legal_name: string };
type DocumentRecord = { id: string; document_type: string; original_filename: string; processing_status: string; created_at: string };
type ExtractedField = { id: string; document_id: string; document_name: string; field_name: string; original_value: string | null; corrected_value: string | null; confidence: number | null; page_number: number | null; source_coordinates: Record<string, number> | null; review_status: string };
type Validation = { id: string; rule_id: string; compared_field: string; status: string; difference: number | null; explanation: string; human_confirmed: boolean };
type Correction = { id: string; field_id: string; field_name: string; document_name: string; original_value: string | null; corrected_value: string | null; reason: string; created_at: string };
type AccuracyReport = { measured_accuracy: number | null; evaluation_sample_size: number; corrected_fields: number; field_wise_accuracy: Record<string, { accuracy: number | null; sample_size: number }>; supplier_wise_accuracy: Record<string, { accuracy: number | null; sample_size: number }>; note: string };

function formatError(detail: unknown, fallback = "Request failed"): string {
  if (typeof detail === "string") return detail;
  if (detail && typeof detail === "object" && "message" in detail) {
    const message = String((detail as { message: string }).message);
    const blockers = (detail as { blockers?: string[] }).blockers;
    return blockers?.length ? `${message}: ${blockers.join("; ")}` : message;
  }
  return fallback;
}

async function request<T>(path: string, init: RequestInit = {}): Promise<T> {
  const headers = new Headers(init.headers);
  const token = localStorage.getItem("access_token");
  if (token) headers.set("Authorization", `Bearer ${token}`);
  if (init.body && !(init.body instanceof FormData)) headers.set("Content-Type", "application/json");
  const response = await fetch(`${API_URL}${path}`, { ...init, headers });
  if (!response.ok) {
    const body = await response.json().catch(() => ({}));
    throw new Error(formatError(body.detail));
  }
  return response.json() as Promise<T>;
}

function isLowConfidence(field: ExtractedField): boolean {
  return field.confidence !== null && field.confidence < 0.7 && !["confirmed", "corrected"].includes(field.review_status);
}

function Login() {
  const navigate = useNavigate();
  const [email, setEmail] = useState("executive@example.com");
  const [password, setPassword] = useState("password");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  async function submit(event: FormEvent) {
    event.preventDefault();
    setBusy(true);
    setError("");
    try {
      const response = await fetch(`${API_URL}/api/auth/login`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ email, password }),
      });
      if (!response.ok) throw new Error("Invalid email or password");
      const data = await response.json() as { access_token: string };
      localStorage.setItem("access_token", data.access_token);
      navigate("/shipments");
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Unable to sign in");
    } finally {
      setBusy(false);
    }
  }
  return (
    <main className="shell">
      <section className="card">
        <p className="eyebrow">CUSTOMS DOCUMENT INTELLIGENCE</p>
        <h1>Sign in</h1>
        <p className="muted">Review shipments, resolve discrepancies, and prepare approved exports.</p>
        <form onSubmit={submit}>
          <label>Email<input value={email} onChange={(event) => setEmail(event.target.value)} type="email" required /></label>
          <label>Password<input value={password} onChange={(event) => setPassword(event.target.value)} type="password" required /></label>
          {error && <p className="error">{error}</p>}
          <button disabled={busy} type="submit">{busy ? "Signing in..." : "Sign in"}</button>
        </form>
        <p className="hint">Demo: executive@example.com or manager@example.com / password</p>
      </section>
    </main>
  );
}

function Shipments() {
  const navigate = useNavigate();
  const [user, setUser] = useState<User | null>(null);
  const [shipments, setShipments] = useState<Shipment[]>([]);
  const [importers, setImporters] = useState<Importer[]>([]);
  const [selected, setSelected] = useState<Shipment | null>(null);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [createForm, setCreateForm] = useState({ shipment_number: "", supplier_name: "", importer_id: "" });

  async function load() {
    const [currentUser, records] = await Promise.all([
      request<User>("/api/auth/me"),
      request<Shipment[]>("/api/shipments"),
    ]);
    setUser(currentUser);
    setShipments(records);
    if (currentUser.role === "executive" || currentUser.role === "manager") {
      const importerList = await request<Importer[]>("/api/shipments/importers");
      setImporters(importerList);
      setCreateForm((current) => ({
        ...current,
        importer_id: current.importer_id || importerList[0]?.id || "",
      }));
    }
  }

  useEffect(() => {
    load().catch((reason: unknown) => {
      localStorage.removeItem("access_token");
      setError(reason instanceof Error ? reason.message : "Unable to load shipments");
    });
  }, []);

  async function createShipment(event: FormEvent) {
    event.preventDefault();
    if (!createForm.importer_id) return;
    setBusy(true);
    setError("");
    try {
      const created = await request<Shipment>("/api/shipments", {
        method: "POST",
        body: JSON.stringify({
          shipment_number: createForm.shipment_number,
          importer_id: createForm.importer_id,
          supplier_name: createForm.supplier_name || null,
        }),
      });
      setCreateForm((current) => ({ ...current, shipment_number: "", supplier_name: "" }));
      await load();
      setSelected(created);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Unable to create shipment");
    } finally {
      setBusy(false);
    }
  }

  if (selected) {
    return (
      <ReviewWorkspace
        shipment={selected}
        user={user}
        onBack={() => {
          setSelected(null);
          load().catch(() => undefined);
        }}
        onShipmentChange={setSelected}
      />
    );
  }

  if (error && !user) {
    return (
      <main className="shell">
        <section className="card">
          <p className="error">{error}</p>
          <button onClick={() => navigate("/login")}>Return to sign in</button>
        </section>
      </main>
    );
  }

  return (
    <div className="app-shell">
      <header className="topbar">
        <div>
          <p className="eyebrow">DOCUMENT CONTROL</p>
          <strong>Shipment workspace</strong>
        </div>
        <div className="account">
          {user?.full_name}
          <span>{user?.role}</span>
          <Link className="secondary link-button" to="/accuracy">Accuracy</Link>
          <button className="secondary" onClick={() => { localStorage.removeItem("access_token"); navigate("/login"); }}>Sign out</button>
        </div>
      </header>
      <main className="content">
        <div className="page-heading">
          <div>
            <p className="eyebrow">OPERATIONS</p>
            <h1>Shipments</h1>
            <p className="muted">Upload documents, review extraction, clear cross-checks, and export for filing.</p>
          </div>
          <button className="secondary" onClick={() => load().catch((reason) => setError(reason instanceof Error ? reason.message : "Refresh failed"))}>Refresh</button>
        </div>
        {error && <div className="notice error-notice">{error}</div>}
        {(user?.role === "executive" || user?.role === "manager") && (
          <section className="panel">
            <div className="panel-heading"><h2>New shipment</h2></div>
            <form className="panel-body create-form" onSubmit={createShipment}>
              <label>Shipment number<input required value={createForm.shipment_number} onChange={(event) => setCreateForm({ ...createForm, shipment_number: event.target.value })} placeholder="SHP-24813" /></label>
              <label>Supplier<input value={createForm.supplier_name} onChange={(event) => setCreateForm({ ...createForm, supplier_name: event.target.value })} placeholder="Supplier name" /></label>
              <label>Importer
                <select required value={createForm.importer_id} onChange={(event) => setCreateForm({ ...createForm, importer_id: event.target.value })}>
                  {importers.map((importer) => <option key={importer.id} value={importer.id}>{importer.legal_name}</option>)}
                </select>
              </label>
              <button disabled={busy || !createForm.importer_id} type="submit">Create</button>
            </form>
          </section>
        )}
        <section className="panel">
          <div className="panel-heading">
            <h2>Shipment queue</h2>
            <span className="count">{shipments.length} records</span>
          </div>
          {shipments.length === 0 ? (
            <div className="empty">No shipments are available for this account.</div>
          ) : (
            <div className="table-wrap">
              <table>
                <thead>
                  <tr><th>Shipment</th><th>Supplier</th><th>Status</th><th>Created</th><th /></tr>
                </thead>
                <tbody>
                  {shipments.map((shipment) => (
                    <tr key={shipment.id}>
                      <td><strong>{shipment.shipment_number}</strong></td>
                      <td>{shipment.supplier_name ?? "—"}</td>
                      <td><span className={`status status-${shipment.status}`}>{shipment.status.replace(/_/g, " ")}</span></td>
                      <td>{new Date(shipment.created_at).toLocaleDateString()}</td>
                      <td><button className="secondary" onClick={() => setSelected(shipment)}>Open review</button></td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </section>
      </main>
    </div>
  );
}

function AccuracyPanel() {
  const [report, setReport] = useState<AccuracyReport | null>(null);
  const [error, setError] = useState("");
  useEffect(() => {
    request<AccuracyReport>("/api/reports/accuracy")
      .then(setReport)
      .catch((reason) => setError(reason instanceof Error ? reason.message : "Unable to load accuracy report"));
  }, []);
  if (error) return <p className="error">{error}</p>;
  if (!report) return <p className="muted">Loading accuracy report...</p>;
  return (
    <div className="accuracy-report">
      <div className="accuracy-summary">
        <strong>{report.measured_accuracy === null ? "Not measured" : `${Math.round(report.measured_accuracy * 100)}%`}</strong>
        <span>{report.evaluation_sample_size} human-verified samples · {report.corrected_fields} corrected fields</span>
      </div>
      <p className="muted">{report.note}</p>
      <div className="accuracy-tables">
        <div>
          <h3>Field-wise</h3>
          {Object.entries(report.field_wise_accuracy).map(([name, value]) => (
            <p key={name}><span>{name}</span><b>{value.accuracy === null ? "—" : `${Math.round(value.accuracy * 100)}%`} ({value.sample_size})</b></p>
          ))}
        </div>
        <div>
          <h3>Supplier-wise</h3>
          {Object.entries(report.supplier_wise_accuracy).map(([name, value]) => (
            <p key={name}><span>{name}</span><b>{value.accuracy === null ? "—" : `${Math.round(value.accuracy * 100)}%`} ({value.sample_size})</b></p>
          ))}
        </div>
      </div>
    </div>
  );
}

function DocumentViewer({
  shipmentId,
  document,
  page,
  zoom,
  coordinates,
  onPageChange,
  onZoomChange,
}: {
  shipmentId: string;
  document: DocumentRecord | null;
  page: number;
  zoom: number;
  coordinates: Record<string, number> | null;
  onPageChange: (page: number) => void;
  onZoomChange: (zoom: number) => void;
}) {
  const [url, setUrl] = useState("");
  const [error, setError] = useState("");
  useEffect(() => {
    let active = true;
    let objectUrl = "";
    setUrl("");
    setError("");
    if (!document) return () => { active = false; };
    fetch(`${API_URL}/api/shipments/${shipmentId}/documents/${document.id}/content`, {
      headers: { Authorization: `Bearer ${localStorage.getItem("access_token")}` },
    })
      .then(async (response) => {
        if (!response.ok) throw new Error("Unable to load private document");
        return response.blob();
      })
      .then((blob) => {
        objectUrl = URL.createObjectURL(blob);
        if (active) setUrl(objectUrl);
      })
      .catch((reason) => {
        if (active) setError(reason instanceof Error ? reason.message : "Unable to load document");
      });
    return () => {
      active = false;
      if (objectUrl) URL.revokeObjectURL(objectUrl);
    };
  }, [shipmentId, document?.id]);
  if (!document) return <div className="viewer-empty">Select a document or source field to preview it.</div>;
  const isPdf = document.original_filename.toLowerCase().endsWith(".pdf");
  const sourceStyle = coordinates
    ? { left: `${coordinates.x ?? 0}px`, top: `${coordinates.y ?? 0}px`, width: `${coordinates.width ?? 0}px`, height: `${coordinates.height ?? 0}px` }
    : undefined;
  return (
    <div className="viewer">
      <div className="viewer-toolbar">
        <strong>{document.original_filename}</strong>
        <label>Page<input type="number" min={1} value={page} onChange={(event) => onPageChange(Math.max(1, Number(event.target.value) || 1))} /></label>
        <button className="secondary" onClick={() => onZoomChange(Math.max(50, zoom - 10))}>−</button>
        <span>{zoom}%</span>
        <button className="secondary" onClick={() => onZoomChange(Math.min(200, zoom + 10))}>+</button>
      </div>
      {error ? <p className="error">{error}</p> : url && (
        <div className="viewer-canvas">
          {isPdf ? (
            <iframe title={document.original_filename} src={`${url}#page=${page}&zoom=${zoom}`} />
          ) : (
            <div className="image-stage">
              <img src={url} alt={document.original_filename} style={{ width: `${zoom}%` }} />
              {sourceStyle && <div className="source-highlight" style={sourceStyle} />}
            </div>
          )}
        </div>
      )}
      <p className="source-note">{coordinates ? "Source coordinates available for this field." : "No source coordinates were captured for this field."}</p>
    </div>
  );
}

function ReviewWorkspace({
  shipment,
  user,
  onBack,
  onShipmentChange,
}: {
  shipment: Shipment;
  user: User | null;
  onBack: () => void;
  onShipmentChange: (shipment: Shipment) => void;
}) {
  const [documents, setDocuments] = useState<DocumentRecord[]>([]);
  const [fields, setFields] = useState<ExtractedField[]>([]);
  const [validations, setValidations] = useState<Validation[]>([]);
  const [corrections, setCorrections] = useState<Correction[]>([]);
  const [documentType, setDocumentType] = useState("invoice");
  const [file, setFile] = useState<File | null>(null);
  const [message, setMessage] = useState("");
  const [busy, setBusy] = useState(false);
  const [correctionValues, setCorrectionValues] = useState<Record<string, string>>({});
  const [selectedDocument, setSelectedDocument] = useState<DocumentRecord | null>(null);
  const [selectedPage, setSelectedPage] = useState(1);
  const [zoom, setZoom] = useState(100);
  const [selectedCoordinates, setSelectedCoordinates] = useState<Record<string, number> | null>(null);

  async function refreshShipment() {
    const latest = await request<Shipment>(`/api/shipments/${shipment.id}`);
    onShipmentChange(latest);
  }

  async function load() {
    const [docs, extracted, results, history] = await Promise.all([
      request<DocumentRecord[]>(`/api/shipments/${shipment.id}/documents`),
      request<ExtractedField[]>(`/api/shipments/${shipment.id}/fields`),
      request<Validation[]>(`/api/shipments/${shipment.id}/validations`),
      request<Correction[]>(`/api/shipments/${shipment.id}/corrections`),
    ]);
    setDocuments(docs);
    setFields(extracted);
    setValidations(results);
    setCorrections(history);
    setSelectedDocument((current) => (current && docs.some((doc) => doc.id === current.id) ? current : docs[0] ?? null));
    setCorrectionValues(Object.fromEntries(extracted.map((field) => [field.id, field.corrected_value ?? field.original_value ?? ""])));
    await refreshShipment();
  }

  useEffect(() => {
    load().catch((reason) => setMessage(reason instanceof Error ? reason.message : "Unable to load review data"));
  }, []);

  async function upload() {
    if (!file) return;
    setBusy(true);
    setMessage("");
    try {
      const body = new FormData();
      body.append("file", file);
      await request(`/api/shipments/${shipment.id}/documents?document_type=${documentType}`, { method: "POST", body });
      setFile(null);
      await load();
      setMessage("Document uploaded privately.");
    } catch (reason) {
      setMessage(reason instanceof Error ? reason.message : "Upload failed");
    } finally {
      setBusy(false);
    }
  }

  async function process(document: DocumentRecord) {
    setBusy(true);
    setMessage("");
    try {
      await request(`/api/shipments/${shipment.id}/documents/${document.id}/process`, { method: "POST" });
      await load();
      setMessage(`${document.original_filename} processed.`);
    } catch (reason) {
      setMessage(reason instanceof Error ? reason.message : "Processing failed");
    } finally {
      setBusy(false);
    }
  }

  async function validate() {
    setBusy(true);
    try {
      setValidations(await request<Validation[]>(`/api/shipments/${shipment.id}/validate`, { method: "POST", body: JSON.stringify({}) }));
      setMessage("Cross-document validations re-run from persisted extraction.");
    } catch (reason) {
      setMessage(reason instanceof Error ? reason.message : "Validation failed");
    } finally {
      setBusy(false);
    }
  }

  async function action(path: string, body?: object) {
    setBusy(true);
    try {
      await request(path, { method: "POST", body: body ? JSON.stringify(body) : undefined });
      await load();
      setMessage("Workflow action completed.");
    } catch (reason) {
      setMessage(reason instanceof Error ? reason.message : "Workflow action failed");
    } finally {
      setBusy(false);
    }
  }

  async function correct(field: ExtractedField) {
    setBusy(true);
    try {
      await request(`/api/shipments/${shipment.id}/fields/${field.id}`, {
        method: "PATCH",
        body: JSON.stringify({ corrected_value: correctionValues[field.id] ?? null, reason: "Human review correction" }),
      });
      await load();
      setMessage("Correction saved and dependent validations cleared.");
    } catch (reason) {
      setMessage(reason instanceof Error ? reason.message : "Correction failed");
    } finally {
      setBusy(false);
    }
  }

  function selectField(field: ExtractedField) {
    setSelectedDocument(documents.find((document) => document.id === field.document_id) ?? null);
    setSelectedPage(field.page_number ?? 1);
    setSelectedCoordinates(field.source_coordinates);
  }

  async function labelGroundTruth(field: ExtractedField) {
    const value = window.prompt(`Human-verified value for ${field.field_name}`, field.corrected_value ?? field.original_value ?? "");
    if (value === null) return;
    setBusy(true);
    try {
      await request(`/api/shipments/${shipment.id}/fields/${field.id}/ground-truth`, {
        method: "POST",
        body: JSON.stringify({ ground_truth_value: value }),
      });
      setMessage("Ground-truth label saved.");
    } catch (reason) {
      setMessage(reason instanceof Error ? reason.message : "Ground-truth label failed");
    } finally {
      setBusy(false);
    }
  }

  async function confirmValidation(result: Validation) {
    setBusy(true);
    try {
      await request(`/api/shipments/${shipment.id}/validations/${result.id}/confirm`, { method: "POST" });
      await load();
      setMessage(`Confirmed cross-check: ${result.compared_field}.`);
    } catch (reason) {
      setMessage(reason instanceof Error ? reason.message : "Unable to confirm validation");
    } finally {
      setBusy(false);
    }
  }

  async function downloadExport(format: "csv" | "xlsx") {
    setBusy(true);
    try {
      const response = await fetch(`${API_URL}/api/shipments/${shipment.id}/export.${format}`, {
        headers: { Authorization: `Bearer ${localStorage.getItem("access_token")}` },
      });
      if (!response.ok) {
        const body = await response.json().catch(() => ({}));
        throw new Error(formatError(body.detail, "Export blocked"));
      }
      const blob = await response.blob();
      const url = URL.createObjectURL(blob);
      const anchor = document.createElement("a");
      anchor.href = url;
      anchor.download = `${shipment.shipment_number}.${format}`;
      anchor.click();
      URL.revokeObjectURL(url);
      await refreshShipment();
      setMessage(`${format.toUpperCase()} export downloaded.`);
    } catch (reason) {
      setMessage(reason instanceof Error ? reason.message : "Export failed");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="app-shell">
      <header className="topbar">
        <div>
          <button className="secondary" onClick={onBack}>← Shipments</button>
          <strong className="workspace-title">{shipment.shipment_number}</strong>
        </div>
        <div className="account">
          {user?.full_name}
          <span>{user?.role}</span>
          <Link className="secondary link-button" to="/accuracy">Accuracy</Link>
        </div>
      </header>
      <main className="content">
        <div className="page-heading">
          <div>
            <p className="eyebrow">REVIEW WORKSPACE</p>
            <h1>{shipment.supplier_name ?? "Supplier pending"}</h1>
            <p className="muted">Document beside fields. Confirm low-confidence values and failed cross-checks before export.</p>
          </div>
          <span className={`status status-${shipment.status}`}>{shipment.status.replace(/_/g, " ")}</span>
        </div>
        {message && <div className="notice">{message}</div>}
        <div className="review-grid">
          <section className="panel">
            <div className="panel-heading"><h2>Documents</h2></div>
            <div className="panel-body">
              <div className="upload-row">
                <select value={documentType} onChange={(event) => setDocumentType(event.target.value)}>
                  <option value="invoice">Invoice</option>
                  <option value="packing_list">Packing list</option>
                  <option value="bill_of_lading">Bill of lading</option>
                </select>
                <input type="file" accept=".pdf,.jpg,.jpeg,.png" onChange={(event) => setFile(event.target.files?.[0] ?? null)} />
                <button disabled={!file || busy} onClick={upload}>Upload</button>
              </div>
              {documents.map((document) => (
                <div className="document-row" key={document.id}>
                  <button
                    className="document-select"
                    onClick={() => {
                      setSelectedDocument(document);
                      setSelectedPage(1);
                      setSelectedCoordinates(null);
                    }}
                  >
                    <strong>{document.original_filename}</strong>
                    <span>{document.document_type} · {document.processing_status}</span>
                  </button>
                  <button className="secondary" disabled={busy} onClick={() => process(document)}>Process</button>
                </div>
              ))}
            </div>
          </section>
          <section className="panel">
            <div className="panel-heading"><h2>Document preview</h2></div>
            <div className="panel-body">
              <DocumentViewer
                shipmentId={shipment.id}
                document={selectedDocument}
                page={selectedPage}
                zoom={zoom}
                coordinates={selectedCoordinates}
                onPageChange={setSelectedPage}
                onZoomChange={setZoom}
              />
            </div>
          </section>
        </div>
        <section className="panel">
          <div className="panel-heading">
            <h2>Extracted fields</h2>
            <span className="count">{fields.length} fields</span>
          </div>
          <div className="panel-body">
            {fields.length === 0 ? (
              <div className="empty">No validated extraction fields yet.</div>
            ) : (
              fields.map((field) => (
                <div className={`field-row ${isLowConfidence(field) ? "field-low-confidence" : ""}`} key={field.id}>
                  <button className="field-source" onClick={() => selectField(field)}>
                    <strong>{field.field_name}</strong>
                    <span>{field.document_name} · page {field.page_number ?? "—"}</span>
                  </button>
                  <div className="field-value">
                    <input
                      value={correctionValues[field.id] ?? ""}
                      onChange={(event) => setCorrectionValues({ ...correctionValues, [field.id]: event.target.value })}
                    />
                    <small>
                      {field.confidence === null ? "No confidence" : `${Math.round(field.confidence * 100)}% confidence`}
                      {" · "}
                      {field.review_status}
                      {isLowConfidence(field) ? " · needs confirmation" : ""}
                    </small>
                  </div>
                  <button className="secondary" disabled={busy} onClick={() => correct(field)}>Save</button>
                  <button className="secondary" disabled={busy} onClick={() => action(`/api/shipments/${shipment.id}/fields/${field.id}/confirm`)}>Confirm</button>
                  <button className="secondary" disabled={busy} onClick={() => labelGroundTruth(field)}>Label ground truth</button>
                </div>
              ))
            )}
          </div>
        </section>
        <section className="panel">
          <div className="panel-heading">
            <h2>Cross-checks</h2>
            <button className="secondary" disabled={busy} onClick={validate}>Run validations</button>
          </div>
          <div className="panel-body">
            {validations.length === 0 ? (
              <div className="empty">No validations have been run.</div>
            ) : (
              validations.map((result) => (
                <div className={`validation-row ${result.status === "failed" && !result.human_confirmed ? "validation-failed" : ""}`} key={result.id}>
                  <span className={`status status-${result.status}`}>{result.status.replace(/_/g, " ")}</span>
                  <div>
                    <strong>{result.compared_field}</strong>
                    <p>{result.explanation}{result.human_confirmed ? " Confirmed by reviewer." : ""}</p>
                  </div>
                  {result.difference !== null && <b>{result.difference}</b>}
                  {(result.status === "failed" || result.status === "needs_review") && !result.human_confirmed && (
                    <button className="secondary" disabled={busy} onClick={() => confirmValidation(result)}>Confirm discrepancy</button>
                  )}
                </div>
              ))
            )}
          </div>
        </section>
        <section className="panel">
          <div className="panel-heading">
            <h2>Edit history</h2>
            <span className="count">{corrections.length} corrections</span>
          </div>
          <div className="panel-body">
            {corrections.length === 0 ? (
              <div className="empty">No corrections logged yet.</div>
            ) : (
              corrections.map((item) => (
                <div className="history-row" key={item.id}>
                  <div>
                    <strong>{item.field_name}</strong>
                    <span>{item.document_name} · {new Date(item.created_at).toLocaleString()}</span>
                  </div>
                  <p>{item.original_value ?? "—"} → {item.corrected_value ?? "—"}</p>
                  <small>{item.reason}</small>
                </div>
              ))
            )}
          </div>
        </section>
        <div className="action-bar">
          {user?.role === "executive" && (
            <button disabled={busy} onClick={() => action(`/api/shipments/${shipment.id}/submit`)}>Submit for approval</button>
          )}
          {user?.role === "manager" && (
            <>
              <button disabled={busy} onClick={() => action(`/api/shipments/${shipment.id}/approve`, { decision: "approved" })}>Approve shipment</button>
              <button className="danger" disabled={busy} onClick={() => action(`/api/shipments/${shipment.id}/approve`, { decision: "rejected" })}>Reject shipment</button>
            </>
          )}
          <button className="secondary" disabled={busy} onClick={() => downloadExport("csv")}>Export CSV</button>
          <button className="secondary" disabled={busy} onClick={() => downloadExport("xlsx")}>Export Excel</button>
        </div>
      </main>
    </div>
  );
}

function App() {
  return (
    <Routes>
      <Route path="/login" element={<Login />} />
      <Route path="/shipments" element={<Shipments />} />
      <Route
        path="/accuracy"
        element={(
          <main className="shell accuracy-shell">
            <section className="card accuracy-card">
              <p className="eyebrow">REPORTING</p>
              <h1>Accuracy report</h1>
              <AccuracyPanel />
              <p className="hint"><Link to="/shipments">← Back to shipments</Link></p>
            </section>
          </main>
        )}
      />
      <Route path="*" element={<Navigate to={localStorage.getItem("access_token") ? "/shipments" : "/login"} replace />} />
    </Routes>
  );
}

createRoot(document.getElementById("root")!).render(
  <React.StrictMode>
    <BrowserRouter>
      <App />
    </BrowserRouter>
  </React.StrictMode>,
);
