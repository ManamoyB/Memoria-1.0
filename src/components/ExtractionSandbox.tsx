import { useState } from 'react';
import { Check, Copy, FileText, Play, RotateCcw, Upload } from 'lucide-react';
import { SAMPLE_PRESETS } from '../data/projectSpec';
import {
  type DocumentFormat,
  type NormalizedDocument,
  type SectionNode,
  buildAgentTaskResponse,
  normalizeDocumentLocally,
} from '../utils/documentNormalizer';

type OutputTab = 'json' | 'blocks' | 'sections' | 'tables' | 'chunks' | 'agent';

function SectionTreeItem({ node, depth = 0 }: { node: SectionNode; depth?: number }) {
  return (
    <div style={{ marginLeft: `${depth * 16}px` }} className="border-l border-slate-200 pl-3 py-1.5">
      <div className="flex items-center gap-2 text-sm">
        <span className="rounded bg-indigo-50 px-1.5 py-0.5 font-mono text-[11px] font-semibold text-indigo-700">
          H{node.level}
        </span>
        <span className="font-medium text-slate-900">{node.title}</span>
        <span className="font-mono text-xs text-slate-400">
          ({node.block_ids.length} blocks)
        </span>
      </div>
      {node.children.map((child) => (
        <SectionTreeItem key={child.section_id} node={child} depth={depth + 1} />
      ))}
    </div>
  );
}

export function ExtractionSandbox() {
  const initial = SAMPLE_PRESETS[0];
  const [selectedPresetId, setSelectedPresetId] = useState<string>(initial.id);
  const [filename, setFilename] = useState<string>(initial.filename);
  const [format, setFormat] = useState<DocumentFormat>(initial.format);
  const [content, setContent] = useState<string>(initial.content);
  const [chunkSize, setChunkSize] = useState<number>(3000);
  const [chunkOverlap, setChunkOverlap] = useState<number>(300);
  const [pageCount, setPageCount] = useState<number | undefined>(initial.pageCount);
  const [ocrPages, setOcrPages] = useState<number[]>(initial.ocrPages ?? []);
  const [outputTab, setOutputTab] = useState<OutputTab>('json');
  const [errorMessage, setErrorMessage] = useState<string | null>(null);
  const [copied, setCopied] = useState(false);

  const [result, setResult] = useState<NormalizedDocument>(() =>
    normalizeDocumentLocally({
      filename: initial.filename,
      format: initial.format,
      content: initial.content,
      pageCount: initial.pageCount,
      ocrPages: initial.ocrPages,
      chunkSize: 3000,
      chunkOverlap: 300,
    }),
  );

  const agentEnvelope = buildAgentTaskResponse({ document: result });

  const handleSelectPreset = (presetId: string) => {
    const found = SAMPLE_PRESETS.find((p) => p.id === presetId);
    if (!found) return;
    setSelectedPresetId(found.id);
    setFilename(found.filename);
    setFormat(found.format);
    setContent(found.content);
    setPageCount(found.pageCount);
    setOcrPages(found.ocrPages ?? []);
    setErrorMessage(null);
    setResult(
      normalizeDocumentLocally({
        filename: found.filename,
        format: found.format,
        content: found.content,
        pageCount: found.pageCount,
        ocrPages: found.ocrPages,
        chunkSize,
        chunkOverlap,
      }),
    );
  };

  const handleRunExtraction = () => {
    if (!filename.trim()) {
      setErrorMessage('Filename is required before running extraction.');
      return;
    }
    if (!Number.isFinite(chunkSize) || chunkSize < 100) {
      setErrorMessage('Chunk size must be at least 100 characters.');
      return;
    }
    if (!Number.isFinite(chunkOverlap) || chunkOverlap < 0 || chunkOverlap >= chunkSize) {
      setErrorMessage('Chunk overlap must be >= 0 and strictly smaller than chunk size.');
      return;
    }
    try {
      setErrorMessage(null);
      const normalized = normalizeDocumentLocally({
        filename: filename.trim(),
        format,
        content,
        pageCount,
        ocrPages,
        chunkSize,
        chunkOverlap,
      });
      setResult(normalized);
    } catch (err) {
      setErrorMessage(err instanceof Error ? err.message : 'Normalization failed.');
    }
  };

  const handleFileUpload = async (event: React.ChangeEvent<HTMLInputElement>) => {
    const file = event.target.files?.[0];
    if (!file) return;
    const ext = file.name.split('.').pop()?.toLowerCase() ?? '';
    let detectedFormat: DocumentFormat = 'txt';
    if (ext === 'md' || ext === 'markdown') detectedFormat = 'markdown';
    else if (ext === 'csv') detectedFormat = 'csv';
    else if (ext === 'txt' || ext === 'text') detectedFormat = 'txt';
    else {
      setErrorMessage(
        `Browser sandbox parses text-based files (.md, .txt, .csv). Use FastAPI /api/v1/documents/process for binary ${ext.toUpperCase()} files.`,
      );
      return;
    }

    const text = await file.text();
    setSelectedPresetId('custom');
    setFilename(file.name);
    setFormat(detectedFormat);
    setContent(text);
    setPageCount(undefined);
    setOcrPages([]);
    setErrorMessage(null);
    try {
      setResult(
        normalizeDocumentLocally({
          filename: file.name,
          format: detectedFormat,
          content: text,
          chunkSize,
          chunkOverlap,
        }),
      );
    } catch (err) {
      setErrorMessage(err instanceof Error ? err.message : 'Failed to parse uploaded file.');
    }
  };

  const handleCopyJson = async () => {
    const payload = outputTab === 'agent' ? agentEnvelope : result;
    await navigator.clipboard.writeText(JSON.stringify(payload, null, 2));
    setCopied(true);
    setTimeout(() => setCopied(false), 1800);
  };

  return (
    <div className="space-y-6">
      <div className="rounded-xl border border-slate-200 bg-white p-5 shadow-xs">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div>
            <h2 className="text-base font-semibold text-slate-900">
              Normalization &amp; Chunking Sandbox
            </h2>
            <p className="text-xs text-slate-600">
              Test deterministic structural extraction, configurable chunking, and inspect{' '}
              <code className="font-mono text-slate-800">NormalizedDocument</code> &amp;{' '}
              <code className="font-mono text-slate-800">AgentTaskResponse</code> payloads.
            </p>
          </div>
          <div className="flex flex-wrap items-center gap-2">
            {SAMPLE_PRESETS.map((preset) => (
              <button
                key={preset.id}
                type="button"
                onClick={() => handleSelectPreset(preset.id)}
                className={`rounded-md border px-3 py-1.5 text-xs font-medium transition-colors ${
                  selectedPresetId === preset.id
                    ? 'border-indigo-600 bg-indigo-50 text-indigo-700'
                    : 'border-slate-200 bg-white text-slate-700 hover:bg-slate-50'
                }`}
              >
                {preset.label}
              </button>
            ))}
          </div>
        </div>
      </div>

      <div className="grid gap-6 lg:grid-cols-12">
        <div className="flex flex-col rounded-xl border border-slate-200 bg-white p-5 shadow-xs lg:col-span-5">
          <div className="grid grid-cols-2 gap-3">
            <div>
              <label
                htmlFor="sandbox-filename"
                className="block text-xs font-medium text-slate-700"
              >
                Source Filename
              </label>
              <input
                id="sandbox-filename"
                type="text"
                value={filename}
                onChange={(e) => {
                  setSelectedPresetId('custom');
                  setFilename(e.target.value);
                }}
                className="mt-1 w-full rounded-md border border-slate-300 px-3 py-1.5 font-mono text-xs text-slate-900 focus:border-indigo-600 focus:outline-none"
              />
            </div>

            <div>
              <label
                htmlFor="sandbox-format"
                className="block text-xs font-medium text-slate-700"
              >
                Document Format
              </label>
              <select
                id="sandbox-format"
                value={format}
                onChange={(e) => {
                  setSelectedPresetId('custom');
                  setFormat(e.target.value as DocumentFormat);
                }}
                className="mt-1 w-full rounded-md border border-slate-300 bg-white px-3 py-1.5 font-mono text-xs text-slate-900 focus:border-indigo-600 focus:outline-none"
              >
                <option value="markdown">markdown (.md)</option>
                <option value="csv">csv (.csv)</option>
                <option value="txt">txt (.txt)</option>
                <option value="pdf">pdf (text simulation)</option>
                <option value="docx">docx (text simulation)</option>
              </select>
            </div>
          </div>

          <div className="mt-3 grid grid-cols-2 gap-3">
            <div>
              <label
                htmlFor="sandbox-chunk-size"
                className="block text-xs font-medium text-slate-700"
              >
                Chunk Size (chars)
              </label>
              <input
                id="sandbox-chunk-size"
                type="number"
                min={100}
                max={50000}
                step={100}
                value={chunkSize}
                onChange={(e) => setChunkSize(Number(e.target.value))}
                className="mt-1 w-full rounded-md border border-slate-300 px-3 py-1.5 font-mono text-xs text-slate-900 focus:border-indigo-600 focus:outline-none"
              />
            </div>
            <div>
              <label
                htmlFor="sandbox-chunk-overlap"
                className="block text-xs font-medium text-slate-700"
              >
                Chunk Overlap (chars)
              </label>
              <input
                id="sandbox-chunk-overlap"
                type="number"
                min={0}
                max={10000}
                step={50}
                value={chunkOverlap}
                onChange={(e) => setChunkOverlap(Number(e.target.value))}
                className="mt-1 w-full rounded-md border border-slate-300 px-3 py-1.5 font-mono text-xs text-slate-900 focus:border-indigo-600 focus:outline-none"
              />
            </div>
          </div>

          <div className="mt-4 flex-1">
            <div className="flex items-center justify-between">
              <label
                htmlFor="sandbox-content"
                className="block text-xs font-medium text-slate-700"
              >
                Raw Document Content
              </label>
              <label className="inline-flex cursor-pointer items-center gap-1.5 text-xs font-medium text-indigo-700 hover:text-indigo-800">
                <Upload className="h-3.5 w-3.5" />
                <span>Load .md / .csv / .txt</span>
                <input
                  type="file"
                  accept=".md,.markdown,.txt,.text,.csv"
                  onChange={handleFileUpload}
                  className="sr-only"
                />
              </label>
            </div>
            <textarea
              id="sandbox-content"
              rows={13}
              value={content}
              onChange={(e) => {
                setSelectedPresetId('custom');
                setContent(e.target.value);
              }}
              placeholder="Paste Markdown, CSV, or plain text content..."
              className="mt-1.5 w-full rounded-lg border border-slate-300 bg-slate-50/50 p-3 font-mono text-xs leading-relaxed text-slate-900 focus:border-indigo-600 focus:bg-white focus:outline-none"
            />
          </div>

          {errorMessage && (
            <div
              role="alert"
              className="mt-3 rounded-md border border-red-200 bg-red-50 px-3 py-2 text-xs text-red-800"
            >
              {errorMessage}
            </div>
          )}

          <div className="mt-4 flex items-center justify-between gap-3">
            <button
              type="button"
              onClick={() => {
                setChunkSize(3000);
                setChunkOverlap(300);
                handleSelectPreset(SAMPLE_PRESETS[0].id);
              }}
              className="inline-flex items-center gap-1.5 rounded-md border border-slate-200 px-3 py-2 text-xs font-medium text-slate-700 hover:bg-slate-50"
            >
              <RotateCcw className="h-3.5 w-3.5" />
              <span>Reset</span>
            </button>
            <button
              type="button"
              onClick={handleRunExtraction}
              className="inline-flex items-center gap-1.5 rounded-md bg-indigo-600 px-4 py-2 text-xs font-semibold text-white hover:bg-indigo-700"
            >
              <Play className="h-3.5 w-3.5" />
              <span>Run Extraction &amp; Normalize</span>
            </button>
          </div>
        </div>

        <div className="flex flex-col rounded-xl border border-slate-200 bg-white p-5 shadow-xs lg:col-span-7">
          <div className="flex flex-wrap items-center justify-between gap-3 border-b border-slate-100 pb-3">
            <div className="flex items-center gap-2">
              <FileText className="h-4 w-4 text-indigo-600" />
              <span className="text-sm font-semibold text-slate-900">
                Standardized Output
              </span>
              <span className="font-mono text-xs text-slate-500">
                {result.metadata.block_count} blocks · {result.metadata.chunk_count} chunks ·{' '}
                {result.metadata.table_count} tables
              </span>
            </div>

            <div className="flex flex-wrap items-center gap-1.5">
              {(
                [
                  ['json', 'JSON'],
                  ['chunks', 'Chunks'],
                  ['blocks', 'Blocks'],
                  ['sections', 'Sections'],
                  ['tables', 'Tables'],
                  ['agent', 'Agent Envelope'],
                ] as [OutputTab, string][]
              ).map(([tab, label]) => (
                <button
                  key={tab}
                  type="button"
                  onClick={() => setOutputTab(tab)}
                  className={`rounded-md px-2.5 py-1 text-xs font-medium transition-colors ${
                    outputTab === tab
                      ? 'bg-slate-900 text-white'
                      : 'text-slate-600 hover:bg-slate-100'
                  }`}
                >
                  {label}
                </button>
              ))}
              <button
                type="button"
                onClick={handleCopyJson}
                aria-label="Copy JSON Output"
                className="ml-1 inline-flex items-center gap-1 rounded-md border border-slate-200 px-2.5 py-1 text-xs font-medium text-slate-700 hover:bg-slate-50"
              >
                {copied ? <Check className="h-3.5 w-3.5 text-emerald-600" /> : <Copy className="h-3.5 w-3.5" />}
                <span>{copied ? 'Copied' : 'Copy JSON'}</span>
              </button>
            </div>
          </div>

          <div className="mt-3 grid grid-cols-1 gap-3 rounded-lg bg-slate-50 p-3 text-xs sm:grid-cols-2 xl:grid-cols-4">
            <div className="min-w-0">
              <span className="block text-[11px] text-slate-500">Document ID</span>
              <span
                title={result.document_id}
                className="block truncate font-mono font-medium text-slate-900"
              >
                {result.document_id}
              </span>
            </div>
            <div className="min-w-0">
              <span className="block text-[11px] text-slate-500">Extractor</span>
              <span
                title={result.metadata.extractor_name}
                className="block truncate font-mono font-medium text-slate-900"
              >
                {result.metadata.extractor_name}
              </span>
            </div>
            <div className="min-w-0">
              <span className="block text-[11px] text-slate-500">Word / Char / Chunks</span>
              <span className="block truncate font-mono font-medium text-slate-900">
                {result.metadata.word_count}w / {result.metadata.char_count}c ({result.metadata.chunk_count})
              </span>
            </div>
            <div className="min-w-0">
              <span className="block text-[11px] text-slate-500">OCR Status</span>
              <span className="block truncate font-mono font-medium text-slate-900">
                {result.ocr.status}
                {result.ocr.pages_requiring_ocr.length > 0
                  ? ` (p.${result.ocr.pages_requiring_ocr.join(',')})`
                  : ''}
              </span>
            </div>
          </div>

          <div className="mt-4 max-h-[430px] overflow-auto">
            {outputTab === 'json' && (
              <pre
                data-testid="normalized-json-output"
                className="rounded-lg bg-slate-950 p-4 font-mono text-xs leading-relaxed text-slate-100"
              >
                {JSON.stringify(result, null, 2)}
              </pre>
            )}

            {outputTab === 'agent' && (
              <pre
                data-testid="agent-envelope-output"
                className="rounded-lg bg-slate-950 p-4 font-mono text-xs leading-relaxed text-slate-100"
              >
                {JSON.stringify(agentEnvelope, null, 2)}
              </pre>
            )}

            {outputTab === 'chunks' && (
              <div className="space-y-2.5">
                {result.chunks.map((chunk) => (
                  <div
                    key={chunk.chunk_id}
                    className="rounded-lg border border-slate-200 bg-slate-50/50 p-3"
                  >
                    <div className="flex flex-wrap items-center justify-between gap-2 text-xs">
                      <div className="flex items-center gap-2">
                        <span className="rounded bg-slate-900 px-1.5 py-0.5 font-mono text-[11px] text-white">
                          Chunk #{chunk.chunk_index}
                        </span>
                        <span className="font-mono text-[11px] text-indigo-700">
                          {chunk.char_count} chars · {chunk.word_count} words
                        </span>
                      </div>
                      <span className="font-mono text-[11px] text-slate-500">
                        {chunk.section_title ?? 'root'}
                        {chunk.page_numbers.length > 0 ? ` · p.${chunk.page_numbers.join(',')}` : ''}
                      </span>
                    </div>
                    <pre className="mt-2 whitespace-pre-wrap font-mono text-xs text-slate-800">
                      {chunk.text}
                    </pre>
                  </div>
                ))}
              </div>
            )}

            {outputTab === 'blocks' && (
              <div className="space-y-2.5">
                {result.blocks.map((block) => (
                  <div
                    key={block.block_id}
                    className="rounded-lg border border-slate-200 bg-slate-50/50 p-3"
                  >
                    <div className="flex flex-wrap items-center justify-between gap-2 text-xs">
                      <div className="flex items-center gap-2">
                        <span className="rounded bg-slate-900 px-1.5 py-0.5 font-mono text-[11px] text-white">
                          #{block.order_index}
                        </span>
                        <span className="rounded bg-indigo-50 px-2 py-0.5 font-mono text-[11px] font-semibold text-indigo-700">
                          {block.type}
                          {block.level ? ` (L${block.level})` : ''}
                        </span>
                      </div>
                      <span className="font-mono text-[11px] text-slate-500">
                        {block.parent_section_id ?? 'root'}
                      </span>
                    </div>
                    <pre className="mt-2 whitespace-pre-wrap font-mono text-xs text-slate-800">
                      {block.text}
                    </pre>
                  </div>
                ))}
              </div>
            )}

            {outputTab === 'sections' && (
              <div className="rounded-lg border border-slate-200 p-4">
                {result.sections.length === 0 ? (
                  <p className="text-sm text-slate-500">
                    No heading hierarchy detected in this document.
                  </p>
                ) : (
                  result.sections.map((section) => (
                    <SectionTreeItem key={section.section_id} node={section} />
                  ))
                )}
              </div>
            )}

            {outputTab === 'tables' && (
              <div className="space-y-4">
                {result.tables.length === 0 ? (
                  <p className="rounded-lg border border-slate-200 p-4 text-sm text-slate-500">
                    No structured tables extracted from this document.
                  </p>
                ) : (
                  result.tables.map((table) => (
                    <div
                      key={table.table_id}
                      className="overflow-x-auto rounded-lg border border-slate-200 p-4"
                    >
                      <div className="mb-2 flex items-center justify-between text-xs">
                        <span className="font-semibold text-slate-900">
                          {table.name ?? table.table_id}
                        </span>
                        <span className="font-mono text-slate-500">
                          {table.row_count} rows × {table.column_count} cols
                        </span>
                      </div>
                      <table className="w-full border-collapse text-left text-xs">
                        <thead>
                          <tr className="border-b border-slate-200 bg-slate-50">
                            {table.headers.map((header, idx) => (
                              <th key={idx} className="px-2.5 py-1.5 font-semibold text-slate-800">
                                {header}
                              </th>
                            ))}
                          </tr>
                        </thead>
                        <tbody className="divide-y divide-slate-100">
                          {table.rows.map((row, rIdx) => (
                            <tr key={rIdx}>
                              {row.map((cell, cIdx) => (
                                <td key={cIdx} className="px-2.5 py-1.5 font-mono text-slate-700">
                                  {cell}
                                </td>
                              ))}
                            </tr>
                          ))}
                        </tbody>
                      </table>
                    </div>
                  ))
                )}
              </div>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}
