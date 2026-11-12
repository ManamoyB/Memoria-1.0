import test from 'node:test';
import assert from 'node:assert/strict';
import {
  buildAgentTaskResponse,
  chunkNormalizedBlocks,
  extractCsvStructure,
  extractMarkdownStructure,
  normalizeDocumentLocally,
  normalizeUnicodeAndWhitespace,
} from './documentNormalizer';

test('normalizeUnicodeAndWhitespace canonicalizes prose and preserves code indentation', () => {
  const prose = normalizeUnicodeAndWhitespace('Cafe\u0301   note\r\n\r\n\r\nNext   line');
  assert.equal(prose, 'Café note\n\nNext line');

  const code = normalizeUnicodeAndWhitespace('  def fn():\r\n      return 42\n', true);
  assert.equal(code, '  def fn():\n      return 42');
});

test('extractMarkdownStructure extracts frontmatter, headings, code blocks, and tables', () => {
  const md = `---
title: Architecture Note
author: Memoria Team
---

# Section One

Paragraph text.

## Subsection

- Item A
- Item B

\`\`\`python
print("ok")
\`\`\`

| Format | Engine |
| --- | --- |
| PDF | PyMuPDF |
`;

  const parsed = extractMarkdownStructure(md);
  assert.equal(parsed.title, 'Architecture Note');
  assert.equal(parsed.author, 'Memoria Team');
  assert.equal(parsed.tables.length, 1);
  assert.deepEqual(parsed.tables[0].headers, ['Format', 'Engine']);
  assert.ok(parsed.blocks.some((b) => b.type === 'code_block'));
  assert.ok(parsed.blocks.some((b) => b.type === 'list_item'));
});

test('extractCsvStructure parses headers, column types, rows, and row blocks', () => {
  const csv = 'id,format,ready\n1,pdf,true\n2,csv,false';
  const parsed = extractCsvStructure(csv, 'agents.csv');
  assert.equal(parsed.tables.length, 1);
  assert.equal(parsed.tables[0].rows.length, 2);
  assert.deepEqual(parsed.tables[0].columnTypes, {
    id: 'integer',
    format: 'string',
    ready: 'boolean',
  });
  assert.equal(parsed.customProperties.row_count, 2);
});

test('normalizeDocumentLocally builds hierarchical sections, chunks, and deterministic document_id', () => {
  const md = `# Overview\n\nCore text.\n\n## Details\n\nNested text.`;
  const first = normalizeDocumentLocally({
    filename: 'spec.md',
    format: 'markdown',
    content: md,
  });
  const second = normalizeDocumentLocally({
    filename: 'spec.md',
    format: 'markdown',
    content: md,
  });

  assert.equal(first.document_id, second.document_id);
  assert.equal(first.filename, 'spec.md');
  assert.equal(first.document_type, 'markdown');
  assert.equal(first.schema_version, '1.0.0');
  assert.equal(first.agent, 'memoria-document-reader');
  assert.equal(first.metadata.section_count, 2);
  assert.equal(first.sections.length, 1);
  assert.equal(first.sections[0].children.length, 1);
  assert.equal(
    first.blocks[3].parent_section_id,
    first.sections[0].children[0].section_id,
  );
  assert.equal(first.chunks.length, 1);
  assert.equal(first.processing_statistics.chunk_count, 1);
  assert.ok(first.content.includes('# Overview'));
});

test('chunkNormalizedBlocks splits large prose respecting chunkSize and overlap', () => {
  const longText = Array.from({ length: 8 }, (_, i) => `Paragraph ${i}: ${'memoria '.repeat(20)}`).join('\n\n');
  const doc = normalizeDocumentLocally({
    filename: 'long.txt',
    format: 'txt',
    content: longText,
    chunkSize: 400,
    chunkOverlap: 60,
  });

  assert.ok(doc.chunks.length >= 3);
  assert.ok(doc.chunks.every((c) => c.char_count > 0 && c.char_count <= 400));
  assert.throws(() =>
    chunkNormalizedBlocks({
      documentId: doc.document_id,
      blocks: doc.blocks,
      sections: doc.sections,
      chunkSize: 200,
      chunkOverlap: 250,
    }),
  );
});

test('buildAgentTaskResponse emits standardized inter-agent envelope', () => {
  const doc = normalizeDocumentLocally({
    filename: 'agent.md',
    format: 'markdown',
    content: '# Title\n\nBody text.',
  });
  const env = buildAgentTaskResponse({ document: doc, taskId: 'orch-123' });
  assert.equal(env.task_id, 'orch-123');
  assert.equal(env.agent_id, 'agent-01-document-reader');
  assert.equal(env.document_id, doc.document_id);
  assert.equal(env.status, 'success');
  assert.equal(env.output_type, 'normalized_document');
  assert.equal(env.next_agent, 'agent-02-context-understanding');
  assert.deepEqual(env.errors, []);
});

test('normalizeDocumentLocally rejects empty content', () => {
  assert.throws(() =>
    normalizeDocumentLocally({
      filename: 'empty.txt',
      format: 'txt',
      content: '   \n  ',
    }),
  );
});
