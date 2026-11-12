import { useState } from 'react';
import { BookOpen, Cpu, FileCode2 } from 'lucide-react';
import { ExtractionSandbox } from './components/ExtractionSandbox';
import { OverviewPanel } from './components/OverviewPanel';
import { SchemaContractPanel } from './components/SchemaContractPanel';

type ActiveTab = 'overview' | 'sandbox' | 'schema';

export default function App() {
  const [activeTab, setActiveTab] = useState<ActiveTab>('overview');

  return (
    <div className="min-h-screen bg-slate-50 text-slate-900">
      <header className="border-b border-slate-200 bg-white">
        <div className="mx-auto flex max-w-7xl flex-wrap items-center justify-between gap-4 px-4 py-4 sm:px-6">
          <div>
            <div className="flex items-center gap-2.5">
              <span className="inline-flex h-8 w-8 items-center justify-center rounded-lg bg-slate-900 font-mono text-xs font-bold text-white">
                M
              </span>
              <div>
                <h1 className="text-base font-semibold tracking-tight text-slate-900 sm:text-lg">
                  MemoriaOS · Document Reader Agent
                </h1>
                <p className="text-xs text-slate-500">
                  Independent ingestion, structural extraction &amp; Pydantic v2 JSON normalization service
                </p>
              </div>
            </div>
          </div>

          <nav aria-label="Workbench sections" className="flex items-center gap-1.5">
            <button
              type="button"
              onClick={() => setActiveTab('overview')}
              className={`inline-flex items-center gap-1.5 rounded-lg px-3 py-2 text-xs font-semibold transition-colors ${
                activeTab === 'overview'
                  ? 'bg-slate-900 text-white'
                  : 'text-slate-600 hover:bg-slate-100 hover:text-slate-900'
              }`}
            >
              <Cpu className="h-3.5 w-3.5" />
              <span>Architecture</span>
            </button>
            <button
              type="button"
              onClick={() => setActiveTab('sandbox')}
              className={`inline-flex items-center gap-1.5 rounded-lg px-3 py-2 text-xs font-semibold transition-colors ${
                activeTab === 'sandbox'
                  ? 'bg-slate-900 text-white'
                  : 'text-slate-600 hover:bg-slate-100 hover:text-slate-900'
              }`}
            >
              <FileCode2 className="h-3.5 w-3.5" />
              <span>Extraction Sandbox</span>
            </button>
            <button
              type="button"
              onClick={() => setActiveTab('schema')}
              className={`inline-flex items-center gap-1.5 rounded-lg px-3 py-2 text-xs font-semibold transition-colors ${
                activeTab === 'schema'
                  ? 'bg-slate-900 text-white'
                  : 'text-slate-600 hover:bg-slate-100 hover:text-slate-900'
              }`}
            >
              <BookOpen className="h-3.5 w-3.5" />
              <span>Schema &amp; API</span>
            </button>
          </nav>
        </div>
      </header>

      <main className="mx-auto max-w-7xl px-4 py-6 sm:px-6">
        {activeTab === 'overview' && <OverviewPanel />}
        {activeTab === 'sandbox' && <ExtractionSandbox />}
        {activeTab === 'schema' && <SchemaContractPanel />}
      </main>
    </div>
  );
}
