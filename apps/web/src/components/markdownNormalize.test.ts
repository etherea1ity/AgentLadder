// @vitest-environment node
import { describe, expect, it } from 'vitest';
import { normalizeMathMarkdown } from '../utils/markdown';

describe('normalizeMathMarkdown', () => {
  it('keeps Big-O as one math expression', () => {
    expect(normalizeMathMarkdown('复杂度是 O(N \\log N)。')).toContain('$O(N \\log N)$');
  });

  it('repairs broken symbol explanation fragments', () => {
    const input = ['f', '(', 't', ')', 'f(t)：时域信号', 'ω', '=', '2πf', 'ω=2πf：角频率'].join('\n');
    const output = normalizeMathMarkdown(input);
    expect(output).toContain('$f(t)$：时域信号');
    expect(output).toContain('ω=2πf：角频率');
    expect(output).not.toContain('f\n(\nt\n)\nf(t)');
  });

  it('converts bracket display math and parenthesized inline math', () => {
    const output = normalizeMathMarkdown('[ F(\\omega) = \\int f(t)\\,dt ]\n符号 ( \\omega = 2\\pi f )');
    expect(output).toContain('$$\nF(\\omega) = \\int f(t)\\,dt\n$$');
    expect(output).toContain('$\\omega = 2\\pi f$');
  });
});
