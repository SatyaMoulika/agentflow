import { describe, expect, it } from 'vitest';
import { renderToStaticMarkup } from 'react-dom/server';
import { RunOutput } from '../src/api/RunOutput';

describe('execution output', () => {
  const nodes = [{ id: 'review', type: 'agent' }];
  it('renders stored agent content as Markdown and keeps the complete output', () => {
    const output = {
      model: 'test-model',
      content: '# PR review\n\n- **Fix login**\n- [View PR](https://example.com/pr/1)',
      tool_calls: [{ tool: 'http_get' }],
    };
    const html = renderToStaticMarkup(
      <RunOutput
        output={output}
        nodes={nodes}
        attempts={[{ node_id: 'review', status: 'succeeded', output }]}
      />,
    );
    expect(html).toContain('<h1>PR review</h1>');
    expect(html).toContain('<strong>Fix login</strong>');
    expect(html).toContain('href="https://example.com/pr/1"');
    expect(html).toContain('View raw output');
    expect(html).toContain('tool_calls');
  });

  it('retains arbitrary business content as JSON', () => {
    const output = { content: '# A business field', customer: 'ACME' };
    const html = renderToStaticMarkup(<RunOutput output={output} nodes={nodes} attempts={[]} />);
    expect(html).toContain('customer');
    expect(html).not.toContain('<h1>');
    expect(html).not.toContain('Generated response');
  });

  it('does not render raw HTML or dangerous links from a model', () => {
    const output = {
      model: 'test',
      content:
        '<script>alert(1)</script> [bad](javascript:alert(1)) ![image](https://example.com/image.png)',
    };
    const html = renderToStaticMarkup(
      <RunOutput
        output={output}
        nodes={nodes}
        attempts={[{ node_id: 'review', status: 'succeeded', output }]}
      />,
    );
    expect(html).not.toContain('<script>');
    expect(html).not.toContain('href="javascript:');
    expect(html).not.toContain('<img');
  });
});
