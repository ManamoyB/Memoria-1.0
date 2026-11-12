import { ArrowRight, CheckCircle2, FolderTree, Layers, ShieldAlert } from 'lucide-react';
import { EXTRACTOR_SPECS, REPOSITORY_TREE } from '../data/projectSpec';

const PIPELINE_STEPS = [
  {
    step: '01',
    title: 'API & Agent Interface',
    module: 'app/api/routes/documents.py · agent.py',
    detail: 'Parses multipart UploadFile or inter-agent task_id and delegates to ProcessingController.',
  },
  {
    step: '02',
    title: 'Detector & Validator',
    module: 'app/services/file_detector.py · file_validator.py',
    detail: 'Verifies size limits, MIME compatibility, magic bytes, OOXML ZIP entries & path safety.',
  },
  {
    step: '03',
    title: 'Independent Extractor',
    module: 'app/extractors/registry.py',
    detail: 'Dispatches by DocumentFormat to PyMuPDF, python-docx, Text, Markdown, or Pandas.',
  },
  {
    step: '04',
    title: 'Normalizer & Chunker',
    module: 'app/services/normalizer.py · chunker.py',
    detail: 'Canonicalizes UTF-8 NFC, builds SectionNode tree & overlapping chunks, emits AgentTaskResponse.',
  },
];

export function OverviewPanel() {
  return (
    <div className="space-y-8">
      <section className="rounded-xl border border-slate-200 bg-white p-6 shadow-xs">
        <div className="flex flex-wrap items-start justify-between gap-4 border-b border-slate-100 pb-5">
          <div>
            <div className="flex items-center gap-2 text-xs font-semibold uppercase tracking-wider text-indigo-700">
              <Layers className="h-4 w-4" />
              <span>Central Processing Pipeline</span>
            </div>
            <h2 className="mt-1 text-lg font-semibold text-slate-900">
              Decoupled Ingestion &amp; Normalization Architecture
            </h2>
            <p className="mt-1 max-w-3xl text-sm text-slate-600">
              Routes stay strictly separate from processing logic. Extractors never import each other
              and emit intermediate DTOs normalized into a deterministic MemoriaOS JSON contract.
            </p>
          </div>
          <span className="rounded-md border border-slate-200 bg-slate-50 px-3 py-1 font-mono text-xs text-slate-700">
            Python 3.12 · FastAPI · Pydantic v2
          </span>
        </div>

        <div className="mt-6 grid gap-4 md:grid-cols-2 xl:grid-cols-4">
          {PIPELINE_STEPS.map((item, idx) => (
            <div
              key={item.step}
              className="relative flex flex-col justify-between rounded-lg border border-slate-200 bg-slate-50/60 p-4"
            >
              <div>
                <div className="flex items-center justify-between">
                  <span className="font-mono text-xs font-semibold text-indigo-700">
                    STAGE {item.step}
                  </span>
                  {idx < PIPELINE_STEPS.length - 1 && (
                    <ArrowRight className="hidden h-4 w-4 text-slate-400 xl:block" />
                  )}
                </div>
                <h3 className="mt-2 text-sm font-semibold text-slate-900">{item.title}</h3>
                <p className="mt-1 text-xs leading-relaxed text-slate-600">{item.detail}</p>
              </div>
              <p className="mt-3 truncate font-mono text-[11px] text-slate-500">{item.module}</p>
            </div>
          ))}
        </div>
      </section>

      <section className="grid gap-6 lg:grid-cols-2">
        <div className="rounded-xl border border-slate-200 bg-white p-6 shadow-xs">
          <div className="flex items-center gap-2 text-sm font-semibold text-emerald-800">
            <CheckCircle2 className="h-4 w-4 text-emerald-600" />
            <span>In Scope — Document Reader Responsibilities</span>
          </div>
          <ul className="mt-4 space-y-2.5 text-sm text-slate-700">
            <li>• Extract text from PDF, DOCX, TXT, Markdown, and CSV independently.</li>
            <li>• Preserve reading order, headings (H1–H6), lists, code blocks, quotes, and tables.</li>
            <li>• Canonicalize UTF-8 NFC &amp; whitespace and emit deterministic SHA-256 IDs.</li>
            <li>• Flag low-text PDF pages for future Tesseract OCR via <code className="font-mono text-xs text-slate-900">OcrEngine</code> hook.</li>
          </ul>
        </div>

        <div className="rounded-xl border border-slate-200 bg-white p-6 shadow-xs">
          <div className="flex items-center gap-2 text-sm font-semibold text-amber-800">
            <ShieldAlert className="h-4 w-4 text-amber-600" />
            <span>Out of Scope — Deferred to Downstream MemoriaOS Agents</span>
          </div>
          <ul className="mt-4 space-y-2.5 text-sm text-slate-700">
            <li>• No LLM summarization, topic classification, or entity extraction.</li>
            <li>• No semantic chunking or vector embeddings generation.</li>
            <li>• No direct Qdrant vector database writes or retrieval queries.</li>
            <li>• No Obsidian Markdown vault formatting or filesystem graph linking.</li>
          </ul>
        </div>
      </section>

      <section className="rounded-xl border border-slate-200 bg-white p-6 shadow-xs">
        <h2 className="text-base font-semibold text-slate-900">
          Independent Extractor Registry
        </h2>
        <p className="mt-1 text-sm text-slate-600">
          Each format engine implements <code className="font-mono text-xs text-slate-800">BaseExtractor</code> and is wired via FastAPI dependency injection.
        </p>

        <div className="mt-4 overflow-x-auto">
          <table className="w-full border-collapse text-left text-sm">
            <thead>
              <tr className="border-b border-slate-200 text-xs font-semibold uppercase tracking-wider text-slate-500">
                <th className="py-2.5 pr-4">Format</th>
                <th className="py-2.5 pr-4">Engine</th>
                <th className="py-2.5 pr-4">Structural Preservation</th>
                <th className="py-2.5 pr-4">Tables</th>
                <th className="py-2.5">OCR Hook</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-100">
              {EXTRACTOR_SPECS.map((spec) => (
                <tr key={spec.format} className="hover:bg-slate-50/70">
                  <td className="py-3 pr-4 font-medium text-slate-900">
                    {spec.label}{' '}
                    <span className="font-mono text-xs text-slate-500">
                      ({spec.extensions.join(', ')})
                    </span>
                  </td>
                  <td className="py-3 pr-4 font-mono text-xs text-indigo-700">{spec.engine}</td>
                  <td className="py-3 pr-4 text-xs text-slate-600">{spec.preservesStructure}</td>
                  <td className="py-3 pr-4 font-mono text-xs">
                    {spec.tables ? (
                      <span className="text-emerald-700">yes</span>
                    ) : (
                      <span className="text-slate-400">no</span>
                    )}
                  </td>
                  <td className="py-3 font-mono text-xs">
                    {spec.ocrReady ? (
                      <span className="text-indigo-700">tesseract-ready</span>
                    ) : (
                      <span className="text-slate-400">n/a</span>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </section>

      <section className="rounded-xl border border-slate-200 bg-white p-6 shadow-xs">
        <div className="flex items-center gap-2 text-sm font-semibold text-slate-900">
          <FolderTree className="h-4 w-4 text-slate-600" />
          <span>Generated Workspace Structure</span>
        </div>
        <pre className="mt-4 overflow-x-auto rounded-lg bg-slate-950 p-4 font-mono text-xs leading-relaxed text-slate-200">
          {REPOSITORY_TREE}
        </pre>
      </section>
    </div>
  );
}
