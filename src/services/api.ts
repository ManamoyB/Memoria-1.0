export type Memory = {
  id: string; title: string; content: string; memory_type: string; status: string;
  version: number; confidence: number; updated_at: string;
  data: { content: string; title: string; sources: { source_id: string; quote: string }[]; tags: string[]; [key: string]: unknown };
};
export type Job = { id: string; kind: string; status: string; error?: string; result?: unknown; created_at: string };
export type Search = { results: { memory: Memory; score: number; explanation: unknown }[]; context: string; warnings: string[] };
export class Api {
  constructor(public key: string) {}
  async request<T>(path: string, options: RequestInit = {}): Promise<T> {
    const headers = new Headers(options.headers);
    headers.set('Authorization', `Bearer ${this.key}`);
    if (options.body && !(options.body instanceof FormData)) headers.set('Content-Type', 'application/json');
    const response = await fetch(`/api/v1${path}`, { ...options, headers });
    const body = await response.json().catch(() => ({}));
    if (!response.ok) throw new Error(body.message || body.detail?.[0]?.msg || `Request failed (${response.status})`);
    return body as T;
  }
  post<T>(path: string, body: unknown = {}) { return this.request<T>(path, { method: 'POST', body: JSON.stringify(body) }); }
}
