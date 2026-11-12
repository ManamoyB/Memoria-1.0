export type DocumentFormat = 'pdf' | 'docx' | 'txt' | 'markdown' | 'csv';

export type BlockType =
  | 'heading'
  | 'paragraph'
  | 'list_item'
  | 'code_block'
  | 'quote'
  | 'table'
  | 'frontmatter';

export interface DocumentBlock {
  block_id: string;
  type: BlockType;
  text: string;
  order_index: number;
  level: number | null;
  page_number: number | null;
  parent_section_id: string | null;
  metadata: Record<string, unknown>;
}

export interface SectionNode {
  section_id: string;
  title: string;
  level: number;
  order_index: number;
  page_number: number | null;
  block_ids: string[];
  children: SectionNode[];
}

export interface PageReference {
  page_number: number;
  char_count: number;
  word_count: number;
  block_count: number;
  is_empty: boolean;
  potentially_scanned: boolean;
  has_images: boolean;
  ocr_applied: boolean;
}

export interface TableData {
  table_id: string;
  name: string | null;
  headers: string[];
  rows: string[][];
  records: Record<string, string>[];
  column_types: Record<string, string>;
  row_count: number;
  total_row_count: number;
  column_count: number;
  truncated: boolean;
  page_number: number | null;
  metadata: Record<string, unknown>;
}

export interface DocumentChunk {
  chunk_id: string;
  document_id: string;
  chunk_index: number;
  text: string;
  char_count: number;
  word_count: number;
  start_char: number;
  end_char: number;
  page_numbers: number[];
  block_ids: string[];
  section_id: string | null;
  section_title: string | null;
}

export interface ProcessingStatistics {
  extraction_time_ms: number;
  normalization_time_ms: number;
  chunking_time_ms: number;
  total_time_ms: number;
  char_count: number;
  word_count: number;
  line_count: number;
  block_count: number;
  section_count: number;
  table_count: number;
  chunk_count: number;
  page_count: number | null;
  empty_page_count: number;
  scanned_page_count: number;
  records_extracted: number | null;
  truncated: boolean;
}

export interface NormalizedDocument {
  schema_version: string;
  agent: string;
  document_id: string;
  filename: string;
  document_type: DocumentFormat;
  status: 'success' | 'partial' | 'failed';
  ingested_at: string;
  source: {
    filename: string;
    extension: string;
    format: DocumentFormat;
    mime_type: string;
    byte_size: number;
    content_hash: string;
    ingested_at: string;
  };
  metadata: {
    title: string | null;
    author: string | null;
    created_at: string | null;
    modified_at: string | null;
    page_count: number | null;
    block_count: number;
    section_count: number;
    table_count: number;
    chunk_count: number;
    word_count: number;
    char_count: number;
    line_count: number;
    encoding: string | null;
    extractor_name: string;
    custom_properties: Record<string, unknown>;
  };
  content: string;
  blocks: DocumentBlock[];
  sections: SectionNode[];
  tables: TableData[];
  pages: PageReference[];
  chunks: DocumentChunk[];
  ocr: {
    status: 'not_needed' | 'deferred_disabled' | 'applied' | 'unavailable';
    ocr_enabled: boolean;
    ocr_applied: boolean;
    ocr_engine: string | null;
    pages_requiring_ocr: number[];
    empty_pages: number[];
    notes: string[];
  };
  processing_statistics: ProcessingStatistics;
  extraction_warnings: string[];
  processing_time_ms: number;
}

export interface AgentTaskResponse {
  task_id: string;
  agent_id: string;
  document_id: string | null;
  status: 'success' | 'partial' | 'failed';
  output_type: 'normalized_document';
  output: NormalizedDocument | null;
  errors: Array<{
    error_code: string;
    message: string;
    details: Record<string, unknown>;
    recoverable: boolean;
  }>;
  metadata: Record<string, unknown>;
  next_agent: string | null;
  timestamp: string;
}

interface RawBlockInput {
  type: BlockType;
  text: string;
  level?: number | null;
  page_number?: number | null;
  metadata?: Record<string, unknown>;
}

interface RawTableInput {
  name: string | null;
  headers: string[];
  rows: string[][];
  columnTypes?: Record<string, string>;
  records?: Record<string, string>[];
  metadata?: Record<string, unknown>;
}

export function normalizeUnicodeAndWhitespace(
  text: string,
  preserveIndentation = false,
): string {
  const nfc = text.normalize('NFC').replace(/\r\n/g, '\n').replace(/\r/g, '\n').replace(/\ufeff/g, '');
  if (preserveIndentation) {
    return nfc
      .split('\n')
      .map((line) => line.replace(/\s+$/, ''))
      .join('\n')
      .replace(/^\n+|\n+$/g, '');
  }
  return nfc
    .split('\n')
    .map((line) => line.replace(/[^\S\n]+/g, ' ').trim())
    .join('\n')
    .replace(/\n{3,}/g, '\n\n')
    .trim();
}

export function deterministicShortHash(input: string): string {
  let h1 = 0xdeadbeef;
  let h2 = 0x41c6ce57;
  for (let i = 0; i < input.length; i += 1) {
    const ch = input.charCodeAt(i);
    h1 = Math.imul(h1 ^ ch, 2654435761);
    h2 = Math.imul(h2 ^ ch, 1597334677);
  }
  h1 = Math.imul(h1 ^ (h1 >>> 16), 2246822507) ^ Math.imul(h2 ^ (h2 >>> 13), 3266489909);
  h2 = Math.imul(h2 ^ (h2 >>> 16), 2246822507) ^ Math.imul(h1 ^ (h1 >>> 13), 3266489909);
  const partA = (h1 >>> 0).toString(16).padStart(8, '0');
  const partB = (h2 >>> 0).toString(16).padStart(8, '0');
  return `${partA}${partB}${partA}${partB}`.slice(0, 32);
}

function deterministicUuid(seed: string): string {
  const hex = deterministicShortHash(seed);
  return `${hex.slice(0, 8)}-${hex.slice(8, 12)}-5${hex.slice(13, 16)}-8${hex.slice(17, 20)}-${hex.slice(20, 32)}`;
}

function splitPipeRow(line: string): string[] {
  let stripped = line.trim();
  if (stripped.startsWith('|')) stripped = stripped.slice(1);
  if (stripped.endsWith('|')) stripped = stripped.slice(0, -1);
  return stripped.split('|').map((cell) => cell.trim());
}

export function extractMarkdownStructure(content: string): {
  blocks: RawBlockInput[];
  tables: RawTableInput[];
  title: string | null;
  author: string | null;
  customProperties: Record<string, unknown>;
} {
  const lines = content.replace(/\r\n/g, '\n').replace(/\r/g, '\n').split('\n');
  let idx = 0;
  const blocks: RawBlockInput[] = [];
  const tables: RawTableInput[] = [];
  const customProperties: Record<string, unknown> = {};
  let title: string | null = null;
  let author: string | null = null;

  if (lines[0]?.trim() === '---') {
    const fmEnd = lines.findIndex((line, i) => i > 0 && line.trim() === '---');
    if (fmEnd > 0) {
      const fmLines = lines.slice(1, fmEnd);
      const fm: Record<string, string> = {};
      for (const fmLine of fmLines) {
        const colonIdx = fmLine.indexOf(':');
        if (colonIdx > 0) {
          const k = fmLine.slice(0, colonIdx).trim();
          const v = fmLine.slice(colonIdx + 1).trim().replace(/^['"]|['"]$/g, '');
          if (k && v) fm[k] = v;
        }
      }
      if (Object.keys(fm).length > 0) {
        customProperties.frontmatter = fm;
        if (fm.title) title = fm.title;
        if (fm.author) author = fm.author;
      }
      blocks.push({
        type: 'frontmatter',
        text: fmLines.join('\n'),
        metadata: { format: 'yaml' },
      });
      idx = fmEnd + 1;
    }
  }

  let paragraphBuf: string[] = [];
  const flushParagraph = () => {
    if (paragraphBuf.length > 0) {
      const joined = paragraphBuf.map((p) => p.trim()).filter(Boolean).join('\n');
      if (joined) blocks.push({ type: 'paragraph', text: joined });
      paragraphBuf = [];
    }
  };

  while (idx < lines.length) {
    const line = lines[idx];
    const stripped = line.trim();
    if (!stripped) {
      flushParagraph();
      idx += 1;
      continue;
    }

    const fenceMatch = stripped.match(/^(`{3,}|~{3,})(.*)$/);
    if (fenceMatch) {
      flushParagraph();
      const fenceChar = fenceMatch[1][0];
      const fenceLen = fenceMatch[1].length;
      const language = fenceMatch[2].trim() || null;
      const codeLines: string[] = [];
      idx += 1;
      while (idx < lines.length) {
        if (lines[idx].trim().startsWith(fenceChar.repeat(fenceLen))) {
          idx += 1;
          break;
        }
        codeLines.push(lines[idx]);
        idx += 1;
      }
      blocks.push({
        type: 'code_block',
        text: codeLines.join('\n'),
        metadata: language ? { language } : {},
      });
      continue;
    }

    const headingMatch = stripped.match(/^(#{1,6})\s+(.+?)\s*#*$/);
    if (headingMatch) {
      flushParagraph();
      const level = headingMatch[1].length;
      const headingText = headingMatch[2].trim();
      if (!title && level === 1) title = headingText;
      blocks.push({ type: 'heading', text: headingText, level });
      idx += 1;
      continue;
    }

    if (
      line.includes('|') &&
      idx + 1 < lines.length &&
      /^\|?\s*:?-{2,}:?\s*(\|\s*:?-{2,}:?\s*)+\|?$/.test(lines[idx + 1].trim())
    ) {
      flushParagraph();
      const headers = splitPipeRow(line);
      idx += 2;
      const rows: string[][] = [];
      while (idx < lines.length && lines[idx].includes('|') && lines[idx].trim()) {
        rows.push(splitPipeRow(lines[idx]));
        idx += 1;
      }
      const records = rows.map((row) =>
        Object.fromEntries(headers.map((h, colIdx) => [h || `col_${colIdx + 1}`, row[colIdx] ?? ''])),
      );
      tables.push({ name: `Table ${tables.length + 1}`, headers, rows, records });
      blocks.push({
        type: 'table',
        text: [headers.join(' | '), ...rows.map((r) => r.join(' | '))].join('\n'),
        metadata: { table_index: tables.length - 1 },
      });
      continue;
    }

    const quoteMatch = stripped.match(/^>\s?(.*)$/);
    if (quoteMatch) {
      flushParagraph();
      const quoteLines = [quoteMatch[1]];
      idx += 1;
      while (idx < lines.length) {
        const nextQuote = lines[idx].trim().match(/^>\s?(.*)$/);
        if (!nextQuote) break;
        quoteLines.push(nextQuote[1]);
        idx += 1;
      }
      blocks.push({ type: 'quote', text: quoteLines.join('\n').trim() });
      continue;
    }

    const listMatch = line.match(/^(\s*)([-*+]|\d+[.)])\s+(.+)$/);
    if (listMatch) {
      flushParagraph();
      const indent = listMatch[1].replace(/\t/g, '  ').length;
      blocks.push({
        type: 'list_item',
        text: listMatch[3].trim(),
        level: Math.min(6, Math.floor(indent / 2) + 1),
        metadata: { marker: listMatch[2] },
      });
      idx += 1;
      continue;
    }

    paragraphBuf.push(line);
    idx += 1;
  }

  flushParagraph();
  return { blocks, tables, title, author, customProperties };
}

function inferColumnType(values: string[]): string {
  const missing = new Set(['', 'na', 'n/a', 'null', 'none', 'nan']);
  const nonEmpty = values.map((v) => v.trim()).filter((v) => !missing.has(v.toLowerCase()));
  if (nonEmpty.length === 0) return 'empty';
  if (nonEmpty.every((v) => /^[+-]?\d+$/.test(v))) return 'integer';
  if (nonEmpty.every((v) => /^[+-]?(\d+(\.\d*)?|\.\d+)$/.test(v))) return 'float';
  if (nonEmpty.every((v) => ['true', 'false', 'yes', 'no'].includes(v.toLowerCase()))) return 'boolean';
  return 'string';
}

export function extractCsvStructure(
  content: string,
  filename: string,
): {
  blocks: RawBlockInput[];
  tables: RawTableInput[];
  customProperties: Record<string, unknown>;
} {
  const lines = content
    .replace(/\r\n/g, '\n')
    .replace(/\r/g, '\n')
    .split('\n')
    .filter((l) => l.trim().length > 0);
  if (lines.length === 0) {
    throw new Error('CSV input is empty.');
  }
  const delimiter = lines[0].includes(';') && !lines[0].includes(',') ? ';' : ',';
  const parseLine = (row: string): string[] => {
    const cells: string[] = [];
    let current = '';
    let inQuotes = false;
    for (let i = 0; i < row.length; i += 1) {
      const ch = row[i];
      if (ch === '"') {
        inQuotes = !inQuotes;
      } else if (ch === delimiter && !inQuotes) {
        cells.push(current.trim());
        current = '';
      } else {
        current += ch;
      }
    }
    cells.push(current.trim());
    return cells;
  };

  const headers = parseLine(lines[0]);
  const rows = lines.slice(1).map(parseLine);
  const columnTypes = Object.fromEntries(
    headers.map((h, idx) => [h, inferColumnType(rows.map((r) => r[idx] ?? ''))]),
  );
  const records = rows.map((row) =>
    Object.fromEntries(headers.map((h, idx) => [h, row[idx] ?? ''])),
  );
  const blocks: RawBlockInput[] = [
    {
      type: 'table',
      text: headers.join(' | '),
      metadata: { table_index: 0, columns: headers, column_types: columnTypes, row_count: rows.length },
    },
    ...rows.map((row, index) => ({
      type: 'paragraph' as const,
      text: headers.map((h, i) => `${h}: ${row[i] ?? ''}`).join('; '),
      metadata: { row_index: index + 1 },
    })),
  ];

  return {
    blocks,
    tables: [
      {
        name: filename.replace(/\.[^.]+$/, ''),
        headers,
        rows,
        columnTypes,
        records,
        metadata: { delimiter },
      },
    ],
    customProperties: {
      delimiter,
      columns: headers,
      column_types: columnTypes,
      row_count: rows.length,
      column_count: headers.length,
    },
  };
}

export function extractPlainTextStructure(content: string): {
  blocks: RawBlockInput[];
} {
  const paragraphs = content
    .replace(/\r\n/g, '\n')
    .replace(/\r/g, '\n')
    .split(/\n\s*\n+/)
    .map((p) => p.trim())
    .filter(Boolean);
  return {
    blocks: paragraphs.map((p) => ({ type: 'paragraph', text: p })),
  };
}

function indexSectionTitles(sections: SectionNode[]): Record<string, string> {
  const map: Record<string, string> = {};
  for (const sec of sections) {
    map[sec.section_id] = sec.title;
    if (sec.children.length > 0) {
      Object.assign(map, indexSectionTitles(sec.children));
    }
  }
  return map;
}

export function chunkNormalizedBlocks(params: {
  documentId: string;
  blocks: DocumentBlock[];
  sections: SectionNode[];
  chunkSize?: number;
  chunkOverlap?: number;
}): DocumentChunk[] {
  const chunkSize = params.chunkSize ?? 3000;
  const chunkOverlap = params.chunkOverlap ?? 300;
  if (chunkSize < 100) {
    throw new Error('chunk_size must be at least 100 characters.');
  }
  if (chunkOverlap < 0 || chunkOverlap >= chunkSize) {
    throw new Error('chunk_overlap must be >= 0 and strictly smaller than chunk_size.');
  }

  const sectionTitles = indexSectionTitles(params.sections);
  const units = params.blocks
    .filter((b) => b.type !== 'frontmatter' && b.text.trim().length > 0)
    .map((b) => ({
      block_id: b.block_id,
      text:
        b.type === 'heading'
          ? `${'#'.repeat(b.level ?? 1)} ${b.text.trim()}`
          : b.type === 'list_item'
            ? `- ${b.text.trim()}`
            : b.text.trim(),
      page_number: b.page_number,
      section_id: b.parent_section_id,
    }));

  if (units.length === 0) return [];

  const measure = (arr: typeof units) =>
    arr.length === 0 ? 0 : arr.reduce((sum, u) => sum + u.text.length, 0) + 2 * (arr.length - 1);

  const chunks: DocumentChunk[] = [];
  let current: typeof units = [];
  let cursorChar = 0;

  const finalize = (batch: typeof units, startChar: number): DocumentChunk => {
    const text = batch.map((u) => u.text).join('\n\n').trim();
    const pageSet = new Set<number>();
    const blockIds: string[] = [];
    let sectionId: string | null = null;
    for (const u of batch) {
      if (u.page_number !== null) pageSet.add(u.page_number);
      if (!blockIds.includes(u.block_id)) blockIds.push(u.block_id);
      if (sectionId === null && u.section_id !== null) sectionId = u.section_id;
    }
    const index = chunks.length;
    return {
      chunk_id: deterministicUuid(`${params.documentId}:chunk:${index}:${text.slice(0, 64)}`),
      document_id: params.documentId,
      chunk_index: index,
      text,
      char_count: text.length,
      word_count: text ? text.split(/\s+/).length : 0,
      start_char: startChar,
      end_char: startChar + text.length,
      page_numbers: Array.from(pageSet).sort((a, b) => a - b),
      block_ids: blockIds,
      section_id: sectionId,
      section_title: sectionId ? (sectionTitles[sectionId] ?? null) : null,
    };
  };

  for (const unit of units) {
    if (unit.text.length > chunkSize) {
      if (current.length > 0) {
        const flushed = finalize(current, cursorChar);
        chunks.push(flushed);
        cursorChar = Math.max(0, flushed.end_char - chunkOverlap);
        current = [];
      }
      let start = 0;
      while (start < unit.text.length) {
        let end = Math.min(start + chunkSize, unit.text.length);
        if (end < unit.text.length) {
          const nl = unit.text.lastIndexOf('\n', end);
          const sp = unit.text.lastIndexOf(' ', end);
          const splitAt = nl > start + Math.floor(chunkSize / 2) ? nl : sp;
          if (splitAt > start + Math.floor(chunkSize / 2)) end = splitAt;
        }
        const piece = unit.text.slice(start, end).trim();
        if (piece) {
          const c = finalize([{ ...unit, text: piece }], cursorChar);
          chunks.push(c);
          cursorChar = Math.max(0, c.end_char - chunkOverlap);
        }
        if (end >= unit.text.length) break;
        start = Math.max(start + 1, end - chunkOverlap);
      }
      continue;
    }

    const projected = measure(current) + (current.length > 0 ? 2 : 0) + unit.text.length;
    if (current.length > 0 && projected > chunkSize) {
      const flushed = finalize(current, cursorChar);
      chunks.push(flushed);
      cursorChar = Math.max(0, flushed.end_char - chunkOverlap);

      const budget = Math.min(chunkOverlap, chunkSize - unit.text.length - 2);
      const retained: typeof units = [];
      let total = 0;
      for (let i = current.length - 1; i >= 0; i -= 1) {
        const cand = current[i];
        const added = cand.text.length + (retained.length > 0 ? 2 : 0);
        if (total + added > budget) break;
        retained.unshift(cand);
        total += added;
      }
      current = retained;
    }
    current.push(unit);
  }

  if (current.length > 0) {
    chunks.push(finalize(current, cursorChar));
  }
  return chunks;
}

function countSections(sections: SectionNode[]): number {
  return sections.reduce((acc, sec) => acc + 1 + countSections(sec.children), 0);
}

export function normalizeDocumentLocally(params: {
  filename: string;
  format: DocumentFormat;
  content: string;
  pageCount?: number | null;
  ocrPages?: number[];
  chunkSize?: number;
  chunkOverlap?: number;
}): NormalizedDocument {
  const trimmed = params.content.trim();
  if (!trimmed) {
    throw new Error('Document content cannot be empty.');
  }

  const start = performance.now();
  const hashHex = deterministicShortHash(`${params.format}:${params.content}`);
  const docId = deterministicUuid(`memoriaos:document:sha256:${hashHex}`);
  const prefix = docId.slice(0, 8);

  let rawBlocks: RawBlockInput[] = [];
  let rawTables: RawTableInput[] = [];
  let explicitTitle: string | null = null;
  let author: string | null = null;
  let customProperties: Record<string, unknown> = {};
  let extractorName = 'plain_text_extractor';

  if (params.format === 'markdown') {
    extractorName = 'markdown_structural_extractor';
    const parsed = extractMarkdownStructure(params.content);
    rawBlocks = parsed.blocks;
    rawTables = parsed.tables;
    explicitTitle = parsed.title;
    author = parsed.author;
    customProperties = parsed.customProperties;
  } else if (params.format === 'csv') {
    extractorName = 'pandas_csv_extractor';
    const parsed = extractCsvStructure(params.content, params.filename);
    rawBlocks = parsed.blocks;
    rawTables = parsed.tables;
    customProperties = parsed.customProperties;
  } else {
    extractorName =
      params.format === 'pdf'
        ? 'pymupdf_pdf_extractor'
        : params.format === 'docx'
          ? 'python_docx_extractor'
          : 'plain_text_extractor';
    if (params.format === 'pdf' || params.format === 'docx') {
      const parsed = extractMarkdownStructure(params.content);
      rawBlocks = parsed.blocks;
      rawTables = parsed.tables;
      explicitTitle = parsed.title;
    } else {
      rawBlocks = extractPlainTextStructure(params.content).blocks;
    }
  }

  const blocks: DocumentBlock[] = [];
  const rootSections: SectionNode[] = [];
  const sectionStack: SectionNode[] = [];
  let sectionCounter = 0;

  for (const raw of rawBlocks) {
    const preserveIndent = raw.type === 'code_block' || raw.type === 'frontmatter';
    const text = normalizeUnicodeAndWhitespace(raw.text, preserveIndent);
    if (!text) continue;

    const orderIndex = blocks.length;
    const blockId = `${prefix}-blk-${String(orderIndex).padStart(4, '0')}`;
    let parentSectionId: string | null = null;

    if (raw.type === 'heading') {
      const level = Math.max(1, Math.min(6, raw.level ?? 1));
      sectionCounter += 1;
      const sectionId = `${prefix}-sec-${String(sectionCounter).padStart(4, '0')}`;
      const node: SectionNode = {
        section_id: sectionId,
        title: text,
        level,
        order_index: orderIndex,
        page_number: raw.page_number ?? (params.format === 'pdf' ? 1 : null),
        block_ids: [blockId],
        children: [],
      };
      while (sectionStack.length > 0 && sectionStack[sectionStack.length - 1].level >= level) {
        sectionStack.pop();
      }
      if (sectionStack.length > 0) {
        sectionStack[sectionStack.length - 1].children.push(node);
      } else {
        rootSections.push(node);
      }
      sectionStack.push(node);
      parentSectionId = sectionId;
    } else if (sectionStack.length > 0) {
      const current = sectionStack[sectionStack.length - 1];
      parentSectionId = current.section_id;
      current.block_ids.push(blockId);
    }

    blocks.push({
      block_id: blockId,
      type: raw.type,
      text,
      order_index: orderIndex,
      level: raw.level ?? null,
      page_number: raw.page_number ?? (params.format === 'pdf' ? 1 : null),
      parent_section_id: parentSectionId,
      metadata: raw.metadata ?? {},
    });
  }

  const tables: TableData[] = rawTables.map((t, index) => ({
    table_id: `${prefix}-tbl-${String(index + 1).padStart(3, '0')}`,
    name: t.name,
    headers: t.headers.map((h) => normalizeUnicodeAndWhitespace(h)),
    rows: t.rows.map((r) => r.map((c) => normalizeUnicodeAndWhitespace(c))),
    records: t.records ?? [],
    column_types: t.columnTypes ?? {},
    row_count: t.rows.length,
    total_row_count: t.rows.length,
    column_count: Math.max(t.headers.length, ...t.rows.map((r) => r.length), 0),
    truncated: false,
    page_number: params.format === 'pdf' ? 1 : null,
    metadata: t.metadata ?? {},
  }));

  const normalizedContent = blocks
    .filter((b) => b.type !== 'frontmatter')
    .map((b) => {
      if (b.type === 'heading') return `${'#'.repeat(b.level ?? 1)} ${b.text}`;
      if (b.type === 'list_item') return `- ${b.text}`;
      return b.text;
    })
    .join('\n\n')
    .trim();

  const chunks = chunkNormalizedBlocks({
    documentId: docId,
    blocks,
    sections: rootSections,
    chunkSize: params.chunkSize,
    chunkOverlap: params.chunkOverlap,
  });

  const ocrPages = params.ocrPages ?? [];
  const totalPages = params.format === 'pdf' ? (params.pageCount ?? 1) : null;
  const pages: PageReference[] =
    totalPages !== null
      ? Array.from({ length: totalPages }, (_, i) => {
          const pNum = i + 1;
          const isOcr = ocrPages.includes(pNum);
          const pBlocks = blocks.filter((b) => b.page_number === pNum);
          const pText = pBlocks.map((b) => b.text).join('\n');
          return {
            page_number: pNum,
            char_count: isOcr ? 0 : pText.length,
            word_count: isOcr || !pText ? 0 : pText.split(/\s+/).length,
            block_count: isOcr ? 0 : pBlocks.length,
            is_empty: isOcr || pText.length === 0,
            potentially_scanned: isOcr,
            has_images: isOcr,
            ocr_applied: false,
          };
        })
      : [];

  const firstHeading = blocks.find((b) => b.type === 'heading')?.text ?? null;
  const title = explicitTitle ?? firstHeading ?? params.filename;
  const wordCount = normalizedContent ? normalizedContent.split(/\s+/).length : 0;
  const lineCount = normalizedContent ? normalizedContent.split('\n').length : 0;
  const extMap: Record<DocumentFormat, { ext: string; mime: string }> = {
    pdf: { ext: '.pdf', mime: 'application/pdf' },
    docx: {
      ext: '.docx',
      mime: 'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
    },
    txt: { ext: '.txt', mime: 'text/plain' },
    markdown: { ext: '.md', mime: 'text/markdown' },
    csv: { ext: '.csv', mime: 'text/csv' },
  };
  const nowIso = new Date().toISOString();
  const elapsed = Math.max(0.4, Number((performance.now() - start).toFixed(2)));
  const sectionCount = countSections(rootSections);

  return {
    schema_version: '1.0.0',
    agent: 'memoria-document-reader',
    document_id: docId,
    filename: params.filename,
    document_type: params.format,
    status: 'success',
    ingested_at: nowIso,
    source: {
      filename: params.filename,
      extension: extMap[params.format].ext,
      format: params.format,
      mime_type: extMap[params.format].mime,
      byte_size: new TextEncoder().encode(params.content).length,
      content_hash: `sha256:${hashHex}`,
      ingested_at: nowIso,
    },
    metadata: {
      title,
      author,
      created_at: null,
      modified_at: null,
      page_count: totalPages,
      block_count: blocks.length,
      section_count: sectionCount,
      table_count: tables.length,
      chunk_count: chunks.length,
      word_count: wordCount,
      char_count: normalizedContent.length,
      line_count: lineCount,
      encoding: 'utf-8',
      extractor_name: extractorName,
      custom_properties: customProperties,
    },
    content: normalizedContent,
    blocks,
    sections: rootSections,
    tables,
    pages,
    chunks,
    ocr: {
      status: ocrPages.length > 0 ? 'deferred_disabled' : 'not_needed',
      ocr_enabled: false,
      ocr_applied: false,
      ocr_engine: 'tesseract',
      pages_requiring_ocr: ocrPages,
      empty_pages: ocrPages,
      notes:
        ocrPages.length > 0
          ? ['Pages flagged below MEMORIA_PDF_MIN_TEXT_CHARS_PER_PAGE; Tesseract OCR disabled.']
          : [],
    },
    processing_statistics: {
      extraction_time_ms: Number((elapsed * 0.5).toFixed(2)),
      normalization_time_ms: Number((elapsed * 0.3).toFixed(2)),
      chunking_time_ms: Number((elapsed * 0.2).toFixed(2)),
      total_time_ms: elapsed,
      char_count: normalizedContent.length,
      word_count: wordCount,
      line_count: lineCount,
      block_count: blocks.length,
      section_count: sectionCount,
      table_count: tables.length,
      chunk_count: chunks.length,
      page_count: totalPages,
      empty_page_count: ocrPages.length,
      scanned_page_count: ocrPages.length,
      records_extracted: params.format === 'csv' ? (tables[0]?.row_count ?? 0) : null,
      truncated: false,
    },
    extraction_warnings:
      ocrPages.length > 0
        ? [`Page ${ocrPages.join(', ')} contains no selectable text.`]
        : [],
    processing_time_ms: elapsed,
  };
}

export function buildAgentTaskResponse(params: {
  document: NormalizedDocument;
  taskId?: string;
  nextAgent?: string;
}): AgentTaskResponse {
  const taskId =
    params.taskId ??
    deterministicUuid(`task:${params.document.document_id}:${params.document.source.content_hash}`);
  return {
    task_id: taskId,
    agent_id: 'agent-01-document-reader',
    document_id: params.document.document_id,
    status: params.document.status,
    output_type: 'normalized_document',
    output: params.document,
    errors: [],
    metadata: {
      source_filename: params.document.filename,
      document_type: params.document.document_type,
      content_hash: params.document.source.content_hash,
      byte_size: params.document.source.byte_size,
      chunk_count: params.document.metadata.chunk_count,
      block_count: params.document.metadata.block_count,
      page_count: params.document.metadata.page_count,
      processing_time_ms: params.document.processing_time_ms,
      ocr_status: params.document.ocr.status,
    },
    next_agent: params.nextAgent ?? 'agent-02-context-understanding',
    timestamp: params.document.ingested_at,
  };
}
