import { useCallback, useEffect, useMemo, useState } from 'react';
import { Activity, BookOpen, Boxes, ChevronRight, FileText, GitBranch, LogOut, Moon, RefreshCw, Search as SearchIcon, Settings, Sun, Workflow } from 'lucide-react';
import { Api, type Job, type Memory, type Search } from '../services/api';
import { ExtractionSandbox } from './ExtractionSandbox';

const sections = [
  ['dashboard', 'Overview', Activity], ['memories', 'Memory explorer', BookOpen],
  ['documents', 'Document workbench', FileText], ['agents', 'Agent control', Workflow],
  ['graph', 'Knowledge graph', GitBranch], ['search', 'Search console', SearchIcon],
  ['obsidian', 'Obsidian', Boxes], ['settings', 'Settings', Settings],
] as const;
const types = ['episodic', 'semantic', 'procedural', 'preference', 'project'];
type Metrics = { total_memories: number; by_type: Record<string, number>; documents: number; pending_review: number; recent_jobs: Job[] };
type Agent = { id: string; name: string; description: string; status: string; execution_count: number; failure_count: number; history?: unknown[] };
type Graph = { entities: { id: string; name: string; entity_type: string }[]; relationships: { id: string; source_id: string; target_id: string; relationship_type: string; memory_id: string }[] };
function Json({ value }: { value: unknown }) { return <pre className="json-view">{JSON.stringify(value, null, 2)}</pre>; }
function Badge({ children }: { children: string }) { return <span className={`badge ${/FAIL|REVIEW|PARTIAL/.test(children) ? 'warn' : ''}`}>{children.replaceAll('_', ' ')}</span>; }
function Empty({ children }: { children: string }) { return <div className="empty"><Boxes size={28} /><p>{children}</p></div>; }

export function ControlCenter() {
  const [key, setKey] = useState('');
  const [draftKey, setDraftKey] = useState('');
  const [tab, setTab] = useState('dashboard');
  const [dark, setDark] = useState(localStorage.getItem('memoria-theme') === 'dark');
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);
  const [revision, setRevision] = useState(0);
  const api = useMemo(() => new Api(key), [key]);
  const [metrics, setMetrics] = useState<Metrics>();
  const [status, setStatus] = useState<Record<string, { available: boolean }>>();
  const [memories, setMemories] = useState<Memory[]>([]);
  const [total, setTotal] = useState(0);
  const [offset, setOffset] = useState(0);
  const [category, setCategory] = useState('');
  const [lifecycle, setLifecycle] = useState('STORED');
  const [selected, setSelected] = useState<Memory>();
  const [edit, setEdit] = useState('');
  const [history, setHistory] = useState<unknown>();
  const [agents, setAgents] = useState<Agent[]>([]);
  const [agentDetail, setAgentDetail] = useState<Agent>();
  const [graph, setGraph] = useState<Graph>({ entities: [], relationships: [] });
  const [graphNode, setGraphNode] = useState('');
  const [query, setQuery] = useState('');
  const [mode, setMode] = useState('hybrid');
  const [topK, setTopK] = useState(10);
  const [tag, setTag] = useState('');
  const [after, setAfter] = useState('');
  const [searchResult, setSearchResult] = useState<Search>();
  const [file, setFile] = useState<File>();
  const [extracted, setExtracted] = useState<Record<string, unknown>>();
  const [chunkSize, setChunkSize] = useState(3000);
  const [job, setJob] = useState<Job>();
  const [text, setText] = useState('');
  const [obsidian, setObsidian] = useState<unknown>();
  const [config, setConfig] = useState<{ infrastructure: unknown; operational: unknown }>();
  const [settingsText, setSettingsText] = useState('');
  const [report, setReport] = useState<unknown>();
  const [credentials, setCredentials] = useState<{ id: string; name: string; scopes: string[]; revoked: boolean }[]>([]);
  const [newKeyName, setNewKeyName] = useState('');
  const [newKeyScope, setNewKeyScope] = useState('read');
  const [createdKey, setCreatedKey] = useState('');
  const [demo, setDemo] = useState(false);

  useEffect(() => { document.documentElement.dataset.theme = dark ? 'dark' : 'light'; localStorage.setItem('memoria-theme', dark ? 'dark' : 'light'); }, [dark]);
  const run = useCallback(async (fn: () => Promise<void>) => {
    setBusy(true); setError('');
    try { await fn(); } catch (e) { setError(e instanceof Error ? e.message : 'Operation failed'); }
    finally { setBusy(false); }
  }, []);
  useEffect(() => {
    if (!key) return;
    let cancelled = false;
    const load = async () => {
      if (tab === 'dashboard') {
        const data = await api.request<Metrics>('/system/metrics'); if (!cancelled) setMetrics(data);
        const health = await api.request<Record<string, { available: boolean }>>('/system/status'); if (!cancelled) setStatus(health);
      } else if (tab === 'memories') {
        const data = await api.request<{ items: Memory[]; total: number }>(`/memory?status=${lifecycle}${category ? `&memory_type=${category}` : ''}&offset=${offset}`);
        if (!cancelled) { setMemories(data.items); setTotal(data.total); }
      } else if (tab === 'agents') {
        const data = await api.request<{ items: Agent[] }>('/agents'); if (!cancelled) setAgents(data.items);
      } else if (tab === 'graph') {
        const data = await api.request<Graph>('/graph/entities'); if (!cancelled) setGraph(data);
      } else if (tab === 'obsidian') {
        const data = await api.request('/obsidian/status'); if (!cancelled) setObsidian(data);
      } else if (tab === 'settings') {
        const data = await api.request<{ infrastructure: unknown; operational: unknown }>('/system/config');
        const keys = await api.request<{ items: typeof credentials }>('/credentials');
        if (!cancelled) { setConfig(data); setSettingsText(JSON.stringify(data.operational, null, 2)); setCredentials(keys.items); }
      }
    };
    void run(load);
    return () => { cancelled = true; };
  }, [key, tab, category, lifecycle, offset, revision, api, run]);
  useEffect(() => {
    if (!job || !['PENDING', 'RUNNING', 'RETRYING'].includes(job.status)) return;
    const timer = window.setInterval(() => { api.request<Job>(`/ingestion/${job.id}`).then(setJob).catch(e => setError(e.message)); }, 2000);
    return () => clearInterval(timer);
  }, [job, api]);
  const refresh = () => setRevision(r => r + 1);
  const select = (memory: Memory) => { setSelected(memory); setEdit(memory.content); setHistory(undefined); };
  const memoryAction = (path: string) => run(async () => {
    if (!selected) return;
    select(await api.post<Memory>(`/memory/${selected.id}/${path}?expected_version=${selected.version}`)); refresh();
  });
  const performSearch = () => run(async () => {
    setSearchResult(await api.post<Search>('/search', { query, mode, top_k: topK,
      memory_type: category || null, tags: tag ? tag.split(',').map(t => t.trim()).filter(Boolean) : [],
      after: after ? new Date(after).toISOString() : null }));
  });

  if (!key) return <div className="login-page"><form className="login-card" onSubmit={e => { e.preventDefault(); setKey(draftKey); setDraftKey(''); }}>
    <div className="brand-icon">M</div><span className="eyebrow">LOCAL MEMORY INFRASTRUCTURE</span>
    <h1>Your context,<br />with continuity.</h1><p>Connect to your MemoriaOS instance to capture, explore, and retrieve persistent knowledge.</p>
    <label>Access key<input autoComplete="off" type="password" required value={draftKey} onChange={e => setDraftKey(e.target.value)} placeholder="mem_…" /></label>
    <button className="primary" type="submit">Open control center <ChevronRight size={16} /></button>
    <small>Use the key printed by the local bootstrap command. It stays in memory for this session.</small>
  </form></div>;

  return <div className="control-center"><aside className="sidebar">
    <div className="brand"><div className="brand-icon">M</div><div><strong>MemoriaOS</strong><small>PERSONAL MEMORY SYSTEM</small></div></div>
    <div className="workspace-label">WORKSPACE <span>LOCAL</span></div>
    <nav aria-label="Main navigation">{sections.map(([id, name, Icon]) => <button key={id} className={tab === id ? 'active' : ''} onClick={() => { setTab(id); setError(''); setReport(undefined); }}><Icon size={18} />{name}{tab === id && <span className="nav-dot" />}</button>)}</nav>
    <div className="sidebar-footer"><div className="local-note"><span className="status-dot" />Your memory. Your machine.</div><button onClick={() => setDark(!dark)}>{dark ? <Sun size={17} /> : <Moon size={17} />}{dark ? 'Light appearance' : 'Dark appearance'}</button><button onClick={() => { setKey(''); setSelected(undefined); setCreatedKey(''); setMetrics(undefined); setStatus(undefined); setMemories([]); setTotal(0); setHistory(undefined); setAgents([]); setAgentDetail(undefined); setGraph({ entities: [], relationships: [] }); setGraphNode(''); setSearchResult(undefined); setExtracted(undefined); setJob(undefined); setText(''); setObsidian(undefined); setConfig(undefined); setSettingsText(''); setReport(undefined); setCredentials([]); setFile(undefined); setTab('dashboard'); }}><LogOut size={17} />Disconnect</button></div>
  </aside><main className="main-content">
    <header className="page-header"><div><div className="eyebrow">MEMORIAOS / {sections.find(s => s[0] === tab)?.[1].toUpperCase()}</div><h1>{sections.find(s => s[0] === tab)?.[1]}</h1><p>{tab === 'dashboard' ? 'A clear view of what your system remembers.' : 'Grounded in sources. Preserved over time.'}</p></div><button disabled={busy} onClick={refresh}><RefreshCw size={15} className={busy ? 'spin' : ''} />Refresh</button></header>
    {error && <div role="alert" className="error-banner">{error}<button onClick={() => setError('')} aria-label="Dismiss error">×</button></div>}
    {busy && <div role="status" className="loading-line">Working…</div>}

    {tab === 'dashboard' && <><div className="hero-strip"><div><span className="eyebrow">KNOWLEDGE, WITH A HISTORY</span><h2>Build on what you already know.</h2><p>Capture information once. Keep the sources, decisions, and connections that make it useful.</p></div><button className="primary" onClick={() => setTab('documents')}>Capture a memory <ChevronRight size={16} /></button></div>
      <div className="metric-grid">{[['Stored memories', metrics?.total_memories], ['Documents ingested', metrics?.documents], ['Awaiting review', metrics?.pending_review]].map(([label, value]) => <section className="metric-card" key={label}><span>{label}</span><strong>{value ?? '—'}</strong><small>{label === 'Awaiting review' ? 'Claims that need a decision' : 'From your local database'}</small></section>)}</div>
      <div className="two-column"><section className="panel"><div className="panel-title"><h2>Memory distribution</h2><span>5 categories</span></div>{types.map(type => <div className="distribution" key={type}><span className={`category-dot ${type}`} /><span>{type}</span><div className="bar"><i style={{ width: `${metrics?.total_memories ? (metrics.by_type[type] || 0) / metrics.total_memories * 100 : 0}%` }} /></div><strong>{metrics ? metrics.by_type[type] ?? 0 : '—'}</strong></div>)}</section><section className="panel"><div className="panel-title"><h2>System connections</h2><span>Live checks</span></div>{['database', 'qdrant', 'ollama', 'obsidian'].map(name => <div className="health-row" key={name}><span>{name}</span><span className={status?.[name]?.available ? 'healthy' : 'muted'}>{status ? status[name]?.available ? 'Connected' : 'Unavailable / disabled' : 'Checking…'}</span></div>)}</section></div>
      <section className="panel"><div className="panel-title"><h2>Recent activity</h2><button className="text-button" onClick={() => setTab('agents')}>View agents →</button></div>{!metrics?.recent_jobs.length ? <Empty>No processing jobs yet. Start with a document or conversation.</Empty> : <div className="table-scroll"><table><thead><tr><th>Job</th><th>Type</th><th>Status</th><th>Created</th></tr></thead><tbody>{metrics.recent_jobs.map(item => <tr key={item.id}><td><button className="text-button mono" onClick={() => { setJob(item); setTab('documents'); }}>{item.id.slice(0, 12)}</button></td><td>{item.kind}</td><td><Badge>{item.status}</Badge></td><td>{new Date(item.created_at).toLocaleString()}</td></tr>)}</tbody></table></div>}</section></>}

    {tab === 'memories' && <><div className="toolbar"><select aria-label="Memory category" value={category} onChange={e => { setCategory(e.target.value); setOffset(0); }}><option value="">All categories</option>{types.map(t => <option key={t}>{t}</option>)}</select><select aria-label="Lifecycle status" value={lifecycle} onChange={e => { setLifecycle(e.target.value); setOffset(0); }}>{['STORED', 'WAITING_FOR_REVIEW', 'ARCHIVED', 'SUPERSEDED', 'DELETED', 'REJECTED'].map(t => <option key={t}>{t}</option>)}</select><span className="muted">{total} memories</span><button onClick={() => setTab('search')}>Search with filters</button></div>
      <div className="two-column"><section className="panel">{!memories.length ? <Empty>No memories match these filters.</Empty> : memories.map(memory => <button className={`memory-card ${selected?.id === memory.id ? 'selected' : ''}`} key={memory.id} onClick={() => select(memory)}><div><span className="eyebrow">{memory.memory_type}</span><span className="muted">v{memory.version}</span></div><h3>{memory.title}</h3><p>{memory.content}</p><small>{Math.round(memory.confidence * 100)}% confidence · {memory.data.tags.join(', ')}</small></button>)}<div className="toolbar"><button disabled={!offset} onClick={() => setOffset(Math.max(0, offset - 50))}>Previous</button><button disabled={offset + 50 >= total} onClick={() => setOffset(offset + 50)}>Next</button></div></section>
      <section className="panel detail-panel">{selected ? <><div className="panel-title"><h2>Memory detail</h2><Badge>{selected.status}</Badge></div><label>Content<textarea rows={6} value={edit} onChange={e => setEdit(e.target.value)} /></label><div className="toolbar"><button disabled={busy || edit === selected.content} className="primary" onClick={() => run(async () => { select(await api.request<Memory>(`/memory/${selected.id}`, { method: 'PATCH', body: JSON.stringify({ expected_version: selected.version, memory: { ...selected.data, content: edit } }) })); refresh(); })}>Save for review</button><button onClick={() => memoryAction('archive')}>Archive</button><button onClick={() => memoryAction('restore')}>Restore for review</button></div>{selected.status === 'WAITING_FOR_REVIEW' && <div className="review-box"><strong>Resolve this claim</strong><p>Review its sources before making it available to retrieval.</p><div className="toolbar">{['keep_both', 'supersede', 'reject'].map(action => <button key={action} onClick={() => run(async () => { select(await api.post<Memory>(`/memory/${selected.id}/review`, { action })); refresh(); })}>{action.replace('_', ' ')}</button>)}</div></div>}<h3>Source provenance</h3>{selected.data.sources.map((source, i) => <blockquote key={i}><small>{source.source_id}</small><p>{source.quote}</p></blockquote>)}<button className="text-button" onClick={() => run(async () => setHistory(await api.request(`/memory/${selected.id}/history`)))}>View revision history</button>{history !== undefined && <Json value={history} />}</> : <Empty>Select a memory to inspect its sources and history.</Empty>}</section></div></>}

    {tab === 'documents' && <><div className="two-column"><section className="panel"><div className="panel-title"><h2>Document capture</h2><FileText size={20} /></div><p className="muted">PDF, DOCX, Markdown, text, and CSV. Extraction runs through Agent 01.</p><label className="upload-box"><FileText size={28} /><strong>{file?.name || 'Choose a document'}</strong><span>Up to the configured server upload limit</span><input type="file" accept=".pdf,.docx,.md,.markdown,.txt,.csv" onChange={e => { setFile(e.target.files?.[0]); setExtracted(undefined); }} /></label><label>Chunk size<input type="number" min={100} max={50000} value={chunkSize} onChange={e => setChunkSize(Number(e.target.value))} /></label><div className="toolbar"><button disabled={!file || busy} onClick={() => run(async () => { const form = new FormData(); form.append('file', file!); setExtracted(await api.request(`/documents/process?chunk_size=${chunkSize}&chunk_overlap=${Math.min(300, Math.floor(chunkSize / 10))}`, { method: 'POST', body: form })); })}>Extract only</button><button disabled={!file || busy} className="primary" onClick={() => run(async () => { const form = new FormData(); form.append('file', file!); setJob(await api.request<Job>('/ingestion/document', { method: 'POST', body: form })); })}>Process full pipeline</button></div></section><section className="panel"><h2>Text & conversation capture</h2><label>Source content<textarea rows={7} value={text} onChange={e => setText(e.target.value)} placeholder="Paste a conversation, project decision, or note…" /></label><button className="primary" disabled={!text.trim() || busy} onClick={() => run(async () => setJob(await api.post<Job>('/ingestion/conversation', { content: text, background: true })))}>Capture conversation</button></section></div>
      {job && <section className="panel"><div className="panel-title"><h2>Processing job</h2><Badge>{job.status}</Badge></div><p className="mono muted">{job.id}</p>{job.error && <p role="alert">{job.error}</p>}<Json value={job.result || job} />{['FAILED', 'WAITING_FOR_REVIEW', 'PARTIALLY_COMPLETED'].includes(job.status) && <button onClick={() => run(async () => setJob(await api.post<Job>(`/ingestion/${job.id}/resume`)))}>Resume after resolving issues</button>}</section>}
      {extracted && <section className="panel"><h2>Extracted document</h2>{['content', 'sections', 'chunks', 'extraction_warnings'].map(field => <details key={field} open={field === 'content'}><summary>{field.replaceAll('_', ' ')}</summary><Json value={extracted[field]} /></details>)}</section>}
      <button className="text-button" onClick={() => setDemo(!demo)}>{demo ? 'Hide' : 'Open'} offline normalization examples (demo only)</button>{demo && <ExtractionSandbox />}</>}

    {tab === 'agents' && <><div className="agent-grid">{agents.map(agent => <section className="panel agent-card" key={agent.id}><div className="panel-title"><Workflow size={22} /><Badge>{agent.status}</Badge></div><h2>{agent.name}</h2><p className="muted">{agent.description}</p><div className="agent-counts"><span><strong>{agent.execution_count}</strong>Executions</span><span><strong>{agent.failure_count}</strong>Failures</span></div><button className="text-button" onClick={() => run(async () => setAgentDetail(await api.request<Agent>(`/agents/${agent.id}`)))}>Inspect execution history →</button></section>)}</div><section className="panel"><h2>Safe manual execution</h2><p className="muted">Manual runs follow the complete validated pipeline, including quality checks.</p><label>Content<textarea value={text} onChange={e => setText(e.target.value)} /></label><button className="primary" disabled={!text.trim() || busy} onClick={() => run(async () => { setJob(await api.post<Job>('/agents/agent-07-orchestrator/execute', { content: text })); setTab('documents'); })}>Run orchestrator</button></section>{agentDetail && <section className="panel"><h2>{agentDetail.name}</h2><Json value={agentDetail.history} /></section>}</>}

    {tab === 'graph' && <section className="panel"><div className="panel-title"><h2>Connected knowledge</h2><span>{graph.entities.length} entities · {graph.relationships.length} relationships</span></div>{!graph.entities.length ? <Empty>Entity connections appear after validated memories are stored.</Empty> : <><div className="graph-canvas"><svg viewBox="0 0 800 500" aria-label="Knowledge graph">{graph.relationships.map(edge => { const a = graph.entities.findIndex(n => n.id === edge.source_id), b = graph.entities.findIndex(n => n.id === edge.target_id); const pos = (i: number) => [400 + Math.cos(i / graph.entities.length * 2 * Math.PI) * 290, 250 + Math.sin(i / graph.entities.length * 2 * Math.PI) * 180]; const [x1, y1] = pos(a), [x2, y2] = pos(b); return <line key={edge.id} x1={x1} y1={y1} x2={x2} y2={y2} className={graphNode && [edge.source_id, edge.target_id].includes(graphNode) ? 'selected-edge' : ''} />; })}{graph.entities.map((node, i) => <g key={node.id} role="button" tabIndex={0} aria-label={node.name} onClick={() => setGraphNode(node.id)} onKeyDown={e => { if (e.key === 'Enter') setGraphNode(node.id); }} transform={`translate(${400 + Math.cos(i / graph.entities.length * 2 * Math.PI) * 290},${250 + Math.sin(i / graph.entities.length * 2 * Math.PI) * 180})`}><circle r={graphNode === node.id ? 16 : 10} /><text y={30} textAnchor="middle">{node.name.slice(0, 24)}</text></g>)}</svg></div><select aria-label="Selected entity" value={graphNode} onChange={e => setGraphNode(e.target.value)}><option value="">All entities</option>{graph.entities.map(n => <option key={n.id} value={n.id}>{n.name} ({n.entity_type})</option>)}</select>{graph.relationships.filter(e => !graphNode || [e.source_id, e.target_id].includes(graphNode)).map(edge => <div className="health-row" key={edge.id}><span>{graph.entities.find(n => n.id === edge.source_id)?.name} <Badge>{edge.relationship_type}</Badge> {graph.entities.find(n => n.id === edge.target_id)?.name}</span><button className="text-button" onClick={() => run(async () => { select(await api.request<Memory>(`/memory/${edge.memory_id}`)); setTab('memories'); })}>Source memory</button></div>)}</>}</section>}

    {tab === 'search' && <><section className="panel"><h2>Find the context you need</h2><form onSubmit={e => { e.preventDefault(); performSearch(); }}><div className="search-input"><SearchIcon size={20} /><input aria-label="Search memories" required value={query} onChange={e => setQuery(e.target.value)} placeholder="What did we decide about the project architecture?" /><button className="primary" disabled={busy}>Search</button></div><div className="filter-grid"><label>Retrieval mode<select value={mode} onChange={e => setMode(e.target.value)}>{['hybrid', 'keyword', 'semantic'].map(m => <option key={m}>{m}</option>)}</select></label><label>Category<select value={category} onChange={e => setCategory(e.target.value)}><option value="">All categories</option>{types.map(t => <option key={t}>{t}</option>)}</select></label><label>Top results<input type="number" min={1} max={100} value={topK} onChange={e => setTopK(Number(e.target.value))} /></label><label>Tags<input value={tag} onChange={e => setTag(e.target.value)} placeholder="Comma separated" /></label><label>Created after<input type="date" value={after} onChange={e => setAfter(e.target.value)} /></label></div></form></section>{searchResult && <>{searchResult.warnings.map(w => <div className="review-box" key={w}>{w}</div>)}{searchResult.results.length ? searchResult.results.map(result => <section className="panel" key={result.memory.id}><div className="panel-title"><button className="text-button" onClick={() => { select(result.memory); setTab('memories'); }}><h2>{result.memory.title}</h2></button><Badge>{result.memory.memory_type}</Badge></div><p>{result.memory.content}</p><small>Rank score {result.score.toFixed(5)} · Confidence {result.memory.confidence}</small><details><summary>Ranking & provenance</summary><Json value={{ explanation: result.explanation, sources: result.memory.data.sources }} /></details></section>) : <Empty>No matching memories found.</Empty>}<section className="panel"><h2>Assembled context</h2><pre className="json-view">{searchResult.context || 'No context within this result set.'}</pre></section></>}</>}

    {tab === 'obsidian' && <><section className="panel"><h2>Your human-readable memory</h2><p className="muted">New revision notes go to the existing vault. Human-edited notes are preserved and reported as conflicts.</p>{obsidian !== undefined && <Json value={obsidian} />}<div className="toolbar"><button className="primary" disabled={busy} onClick={() => run(async () => { setReport(await api.post('/obsidian/sync')); refresh(); })}>Retry pending writes</button><button disabled={busy} onClick={() => run(async () => setReport(await api.post('/obsidian/reconcile')))}>Reconcile missing notes</button></div></section>{report !== undefined && <section className="panel"><h2>Synchronization report</h2><Json value={report} /></section>}</>}

    {tab === 'settings' && <><div className="two-column"><section className="panel"><h2>Operational settings</h2><label>Validated configuration<textarea className="mono" rows={12} value={settingsText} onChange={e => setSettingsText(e.target.value)} /></label><button disabled={busy} className="primary" onClick={() => run(async () => { await api.request('/system/config', { method: 'PATCH', body: JSON.stringify(JSON.parse(settingsText)) }); refresh(); })}>Save settings</button><h3>Memory maintenance</h3><div className="toolbar">{[true, false].map(dry => <button key={String(dry)} onClick={() => run(async () => { setJob(await api.post<Job>('/consolidation/run', { dry_run: dry })); setTab('documents'); })}>{dry ? 'Preview consolidation' : 'Run consolidation'}</button>)}</div></section><section className="panel"><h2>Infrastructure</h2><p className="muted">Connection settings come from your environment. Restart after changes. Embedding changes require explicit re-indexing.</p><Json value={config?.infrastructure} /></section></div><section className="panel"><h2>External-agent credentials</h2><div className="toolbar"><input aria-label="Credential name" value={newKeyName} onChange={e => setNewKeyName(e.target.value)} placeholder="Agent name" /><select aria-label="Credential scope" value={newKeyScope} onChange={e => setNewKeyScope(e.target.value)}>{['read', 'write', 'execute'].map(s => <option key={s}>{s}</option>)}</select><button disabled={!newKeyName || busy} onClick={() => run(async () => { const value = await api.post<{ token: string }>('/credentials', { name: newKeyName, scopes: [newKeyScope] }); setCreatedKey(value.token); refresh(); })}>Create key</button></div>{createdKey && <div className="review-box"><p>Copy this key now. It is shown only in this session.</p><code>{createdKey}</code><button onClick={() => setCreatedKey('')}>Hide</button></div>}{credentials.map(c => <div className="health-row" key={c.id}><span>{c.name} · {c.scopes.join(', ')} {c.revoked && '(revoked)'}</span><button disabled={c.revoked} onClick={() => run(async () => { await api.request(`/credentials/${c.id}`, { method: 'DELETE' }); refresh(); })}>Revoke</button></div>)}</section></>}
    <footer className="page-footer"><span>MemoriaOS 1.0</span><span>Persistent context. Traceable knowledge.</span></footer>
  </main></div>;
}
