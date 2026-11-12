import { AGENT_TARGETS, API_ENDPOINTS, ERROR_MATRIX } from '../data/projectSpec';

const SCHEMA_FIELDS = [
  { field: 'schema_version', type: 'str', note: 'Contract version ("1.0.0") for downstream agents' },
  { field: 'agent', type: 'str', note: 'Fixed producer identifier ("memoria-document-reader")' },
  { field: 'document_id', type: 'str', note: 'Deterministic UUIDv5 derived from SHA-256 content hash' },
  { field: 'filename / document_type', type: 'str / DocumentFormat', note: 'Sanitized filename and canonical format (pdf | docx | txt | markdown | csv)' },
  { field: 'status', type: 'ExtractionStatus', note: 'success | partial | failed' },
  { field: 'source', type: 'DocumentSource', note: 'filename, extension, format, mime_type, byte_size, content_hash' },
  { field: 'metadata', type: 'DocumentMetadata', note: 'title, author, counts, encoding, extractor_name, custom_properties' },
  { field: 'content', type: 'str', note: 'Canonical UTF-8 NFC text assembled in reading order' },
  { field: 'blocks / sections / tables', type: 'list[...]', note: 'Ordered DocumentBlock[], SectionNode[] tree, and TableData[]' },
  { field: 'pages / chunks', type: 'list[PageReference] / list[DocumentChunk]', note: 'Per-page telemetry and overlapping RAG chunks (3000 chars / 300 overlap default)' },
  { field: 'ocr', type: 'OcrMetadata', note: 'OCR status, pages_requiring_ocr, empty_pages, and Tesseract diagnostics' },
  { field: 'processing_statistics', type: 'ProcessingStatistics', note: 'Stage timings, word/char/page counts, records_extracted, truncated' },
];

export function SchemaContractPanel() {
  return (
    <div className="space-y-6">
      <section className="rounded-xl border border-slate-200 bg-white p-6 shadow-xs">
        <h2 className="text-base font-semibold text-slate-900">
          FastAPI Endpoints (OpenAPI &amp; Render-Ready)
        </h2>
        <p className="mt-1 text-sm text-slate-600">
          Run locally with <code className="font-mono text-xs text-slate-800">uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload</code> or deploy via <code className="font-mono text-xs text-slate-800">render.yaml</code>.
        </p>

        <div className="mt-4 divide-y divide-slate-100 rounded-lg border border-slate-200">
          {API_ENDPOINTS.map((ep) => (
            <div key={ep.path} className="flex flex-wrap items-center justify-between gap-3 p-4">
              <div className="flex items-center gap-3">
                <span
                  className={`rounded px-2 py-0.5 font-mono text-xs font-semibold ${
                    ep.method === 'GET'
                      ? 'bg-emerald-50 text-emerald-700'
                      : 'bg-indigo-50 text-indigo-700'
                  }`}
                >
                  {ep.method}
                </span>
                <code className="font-mono text-sm font-medium text-slate-900">{ep.path}</code>
              </div>
              <p className="text-xs text-slate-600">{ep.summary}</p>
              <span className="font-mono text-xs text-slate-500">→ {ep.responseSchema}</span>
            </div>
          ))}
        </div>
      </section>

      <section className="rounded-xl border border-slate-200 bg-white p-6 shadow-xs">
        <h2 className="text-base font-semibold text-slate-900">
          Standardized <code className="font-mono text-sm">NormalizedDocument</code> Contract (Pydantic v2)
        </h2>
        <div className="mt-4 overflow-x-auto">
          <table className="w-full border-collapse text-left text-sm">
            <thead>
              <tr className="border-b border-slate-200 text-xs font-semibold uppercase tracking-wider text-slate-500">
                <th className="py-2 pr-4">Field</th>
                <th className="py-2 pr-4">Type</th>
                <th className="py-2">MemoriaOS Purpose</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-100">
              {SCHEMA_FIELDS.map((item) => (
                <tr key={item.field}>
                  <td className="py-2.5 pr-4 font-mono text-xs font-semibold text-slate-900">
                    {item.field}
                  </td>
                  <td className="py-2.5 pr-4 font-mono text-xs text-indigo-700">{item.type}</td>
                  <td className="py-2.5 text-xs text-slate-600">{item.note}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </section>

      <section className="rounded-xl border border-slate-200 bg-white p-6 shadow-xs">
        <h2 className="text-base font-semibold text-slate-900">
          Inter-Agent Routing Targets (<code className="font-mono text-sm">AgentTaskResponse</code>)
        </h2>
        <p className="mt-1 text-sm text-slate-600">
          Every completed extraction exposes <code className="font-mono text-xs text-slate-800">task_id</code>, <code className="font-mono text-xs text-slate-800">agent_id</code>, <code className="font-mono text-xs text-slate-800">document_id</code>, <code className="font-mono text-xs text-slate-800">status</code>, <code className="font-mono text-xs text-slate-800">output_type</code>, <code className="font-mono text-xs text-slate-800">output</code>, <code className="font-mono text-xs text-slate-800">errors</code>, <code className="font-mono text-xs text-slate-800">metadata</code>, and <code className="font-mono text-xs text-slate-800">next_agent</code>.
        </p>
        <div className="mt-4 overflow-x-auto">
          <table className="w-full border-collapse text-left text-sm">
            <thead>
              <tr className="border-b border-slate-200 text-xs font-semibold uppercase tracking-wider text-slate-500">
                <th className="py-2 pr-4">Agent ID</th>
                <th className="py-2 pr-4">Role</th>
                <th className="py-2">Integration Responsibility</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-100">
              {AGENT_TARGETS.map((target) => (
                <tr key={target.id}>
                  <td className="py-2.5 pr-4 font-mono text-xs font-semibold text-indigo-700">
                    {target.id}
                  </td>
                  <td className="py-2.5 pr-4 text-xs font-medium text-slate-900">{target.role}</td>
                  <td className="py-2.5 text-xs text-slate-600">{target.note}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </section>

      <section className="rounded-xl border border-slate-200 bg-white p-6 shadow-xs">
        <h2 className="text-base font-semibold text-slate-900">
          Centralized Error Handling (<code className="font-mono text-sm">ErrorResponse</code>)
        </h2>
        <div className="mt-4 overflow-x-auto">
          <table className="w-full border-collapse text-left text-sm">
            <thead>
              <tr className="border-b border-slate-200 text-xs font-semibold uppercase tracking-wider text-slate-500">
                <th className="py-2 pr-4">HTTP</th>
                <th className="py-2 pr-4">Error Code</th>
                <th className="py-2">Trigger Condition</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-100">
              {ERROR_MATRIX.map((err) => (
                <tr key={err.code}>
                  <td className="py-2.5 pr-4 font-mono text-xs font-semibold text-slate-900">
                    {err.http}
                  </td>
                  <td className="py-2.5 pr-4 font-mono text-xs text-rose-700">{err.code}</td>
                  <td className="py-2.5 text-xs text-slate-600">{err.trigger}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </section>
    </div>
  );
}
