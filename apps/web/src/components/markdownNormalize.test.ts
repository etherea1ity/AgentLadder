// @vitest-environment node
import { describe, expect, it } from 'vitest';
import {
  normalizeGeneratedImagesMarkdown,
  normalizeMathMarkdown,
} from '../utils/markdown';

describe('normalizeMathMarkdown', () => {
  it('keeps Big-O as one math expression', () => {
    expect(normalizeMathMarkdown('\u590d\u6742\u5ea6\u662f O(N \\log N)\u3002')).toContain('$O(N \\log N)$');
  });

  it('repairs broken symbol explanation fragments', () => {
    const input = ['f', '(', 't', ')', 'f(t)\uff1a\u65f6\u57df\u4fe1\u53f7', 'ω', '=', '2πf', 'ω=2πf\uff1a\u89d2\u9891\u7387'].join('\n');
    const output = normalizeMathMarkdown(input);
    expect(output).toContain('$f(t)$\uff1a\u65f6\u57df\u4fe1\u53f7');
    expect(output).toContain('ω=2πf\uff1a\u89d2\u9891\u7387');
    expect(output).not.toContain('f\n(\nt\n)\nf(t)');
  });

  it('converts bracket display math and parenthesized inline math', () => {
    const output = normalizeMathMarkdown('[ F(\\omega) = \\int f(t)\\,dt ]\n\u7b26\u53f7 ( \\omega = 2\\pi f )');
    expect(output).toContain('$$\nF(\\omega) = \\int f(t)\\,dt\n$$');
    expect(output).toContain('$\\omega = 2\\pi f$');
  });
  it('renders bare generated image asset links as markdown images', () => {
    const url = '/api/assets/local?path=data/assets/images/20260617/sample.png';
    const output = normalizeGeneratedImagesMarkdown(`Done\n${url}`);

    expect(output).toContain(`![Generated image](${url})`);
  });

  it('keeps generated image markdown out of math normalization', () => {
    const url = '/api/assets/local?path=data/assets/images/20260617/sample.png';
    const output = normalizeMathMarkdown(`![Generated image](${url})`);

    expect(output).toBe(`![Generated image](${url})`);
  });

  it('repairs broken generated image markdown', () => {
    const url = '/api/assets/local?path=data/assets/images/20260617/sample.png';
    const output = normalizeGeneratedImagesMarkdown(`![Generated image]\n${url}`);

    expect(output).toBe(`![Generated image](${url})`);
  });

  it('converts generated image markdown links back into images', () => {
    const url = 'http://127.0.0.1:8011/api/assets/local?path=data/assets/images/20260617/sample.png';
    const output = normalizeGeneratedImagesMarkdown(`[Open generated image](${url})`);

    expect(output).toBe(`![Generated image](${url})`);
  });

  it('keeps absolute generated image links out of math normalization', () => {
    const url = 'http://127.0.0.1:8011/api/assets/local?path=data/assets/images/20260617/sample.png';
    const output = normalizeMathMarkdown(`[Open generated image](${url})`);

    expect(output).toBe(`![Generated image](${url})`);
  });

  it('repairs local image urls split across tiny lines', () => {
    const output = normalizeGeneratedImagesMarkdown(
      [
        '![Generated image]',
        '/',
        'api',
        '/',
        'assets',
        '/',
        'local',
        '?path=',
        'data',
        '/',
        'assets',
        '/',
        'images',
        '/',
        '20260617',
        '/',
        'sample.png',
      ].join('\n'),
    );

    expect(output).toBe(
      '![Generated image](/api/assets/local?path=data/assets/images/20260617/sample.png)',
    );
  });
});
