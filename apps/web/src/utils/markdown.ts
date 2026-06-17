export function normalizeMathMarkdown(value: string) {
  const imageReady = normalizeGeneratedImagesMarkdown(value);
  const repaired = repairBrokenSymbolExplanations(imageReady);
  const placeholders: string[] = [];
  const stash = (text: string) => {
    const index = placeholders.push(text) - 1;
    return `@@AGENT_LADDER_MD_${index}@@`;
  };
  const protect = (text: string, pattern: RegExp) => text.replace(pattern, (match) => stash(match));

  let text = repaired;
  text = protect(text, /```[\s\S]*?```/g);
  text = protect(text, /`[^`]*`/g);
  text = protect(text, /!?\[[^\]\n]*\]\([^)\n]+\)/g);
  text = protect(text, /\$\$[\s\S]*?\$\$/g);
  text = protect(text, /\$[^$\n]+\$/g);

  text = text.replace(/^\s*\[\s*([^\]\n]+)\s*\]\s*$/gm, (_match, formula) => stash(`$$\n${formula.trim()}\n$$`));
  text = normalizeBigO(text, stash);
  text = normalizeSymbolLabels(text, stash);
  text = normalizeBalancedParenMath(text, stash);

  return text.replace(/@@AGENT_LADDER_MD_(\d+)@@/g, (_match, index) => placeholders[Number(index)] ?? '');
}

const LOCAL_IMAGE_URL_SOURCE =
  '(?:https?:\\/\\/(?:localhost|127\\.0\\.0\\.1|\\[::1\\])(?::\\d+)?)?\\/api\\/assets\\/local\\?path=data\\/assets\\/images\\/[^\\s)]+?\\.(?:png|jpg|jpeg|webp|gif|svg)';
const LOCAL_IMAGE_URL = new RegExp(LOCAL_IMAGE_URL_SOURCE, 'gi');
const MARKDOWN_LOCAL_IMAGE_LINK = new RegExp(
  `\\[([^\\]\\n]*)\\]\\((${LOCAL_IMAGE_URL_SOURCE})\\)`,
  'gi',
);
const MARKDOWN_LOCAL_IMAGE = new RegExp(
  `!\\[[^\\]\\n]*\\]\\(${LOCAL_IMAGE_URL_SOURCE}\\)`,
  'gi',
);

export function normalizeGeneratedImagesMarkdown(value: string) {
  let text = repairSplitLocalImageUrls(value);
  text = text.replace(
    /!\[([^\]\n]*)\]\s*(\/api\/assets\/local\?path=data\/assets\/images\/[^\s)]+?\.(?:png|jpg|jpeg|webp|gif|svg))/gi,
    (_match, alt, url) => `![${alt || 'Generated image'}](${url})`,
  );
  text = text.replace(
    /!\[([^\]\n]*)\]\s*\n+\s*(\/api\/assets\/local\?path=data\/assets\/images\/[^\s)]+?\.(?:png|jpg|jpeg|webp|gif|svg))/gi,
    (_match, alt, url) => `![${alt || 'Generated image'}](${url})`,
  );
  text = text.replace(
    /!\[([^\]\n]*)\]\((\/api\/assets\/local\?path=data\/assets\/images\/[^\s)]+?\.(?:png|jpg|jpeg|webp|gif|svg))\)\s*\n+\s*\2/gi,
    (_match, alt, url) => `![${alt || 'Generated image'}](${url})`,
  );
  return protectExistingMarkdownImages(text, (unprotected) => {
    const linkedImages = unprotected.replace(
      MARKDOWN_LOCAL_IMAGE_LINK,
      (_match, label, url) => `![${generatedImageAlt(label)}](${url})`,
    );
    return linkedImages.replace(LOCAL_IMAGE_URL, (url, offset, fullText) => {
      const before = fullText.slice(Math.max(0, offset - 3), offset);
      if (before.endsWith('](')) return url;
      return `![Generated image](${url})`;
    });
  });
}

function generatedImageAlt(value: string) {
  const label = value.trim();
  if (!label || /^open generated image$/i.test(label)) return 'Generated image';
  return label;
}

function repairSplitLocalImageUrls(value: string) {
  const lines = value.split('\n');
  const repaired: string[] = [];
  let index = 0;

  while (index < lines.length) {
    const line = lines[index];
    if (line.trim() !== '/') {
      repaired.push(line);
      index += 1;
      continue;
    }

    let candidate = '';
    let cursor = index;
    let matched = false;
    while (cursor < lines.length && isLocalImageUrlFragment(lines[cursor])) {
      candidate += lines[cursor].trim();
      if (isCompleteLocalImageUrl(candidate)) {
        repaired.push(candidate);
        index = cursor + 1;
        matched = true;
        break;
      }
      if (candidate.length > 260) break;
      cursor += 1;
    }

    if (!matched) {
      repaired.push(line);
      index += 1;
    }
  }

  return repaired.join('\n');
}

function isLocalImageUrlFragment(line: string) {
  const text = line.trim();
  return text.length > 0 && text.length <= 32 && /^[A-Za-z0-9_./?=&%-]+$/.test(text);
}

function isCompleteLocalImageUrl(value: string) {
  return new RegExp(`^${LOCAL_IMAGE_URL_SOURCE}$`, 'i').test(value);
}

function protectExistingMarkdownImages(
  value: string,
  transform: (text: string) => string,
) {
  const placeholders: string[] = [];
  const protectedText = value.replace(
    MARKDOWN_LOCAL_IMAGE,
    (match) => {
      const index = placeholders.push(match) - 1;
      return `@@KLARA_IMAGE_${index}@@`;
    },
  );
  return transform(protectedText).replace(
    /@@KLARA_IMAGE_(\d+)@@/g,
    (_match, index) => placeholders[Number(index)] ?? '',
  );
}

function normalizeBigO(value: string, stash: (text: string) => string) {
  return value.replace(/(?<![$A-Za-z])O\(([^\n()]{1,80})\)/g, (_match, formula) => stash(`$O(${formula.trim()})$`));
}

function normalizeSymbolLabels(value: string, stash: (text: string) => string) {
  return value.replace(/(^|\n)([A-Za-zωΩπ][A-Za-z0-9ωΩπ]*\([^\n)]{1,50}\))(?=[：:])/g, (_match, prefix, expr) => `${prefix}${stash(`$${expr}$`)}`);
}

function normalizeBalancedParenMath(value: string, stash: (text: string) => string) {
  let result = '';
  let index = 0;
  while (index < value.length) {
    if (value[index] !== '(') {
      result += value[index];
      index += 1;
      continue;
    }

    const end = findMatchingParen(value, index);
    if (end === -1) {
      result += value[index];
      index += 1;
      continue;
    }

    const content = value.slice(index + 1, end).trim();
    if (shouldRenderAsInlineMath(content, value[index - 1], value[end + 1])) {
      result += stash(`$${content}$`);
    } else {
      result += value.slice(index, end + 1);
    }
    index = end + 1;
  }
  return result;
}

function findMatchingParen(value: string, start: number) {
  let depth = 0;
  for (let index = start; index < value.length; index += 1) {
    const char = value[index];
    if (char === '(') depth += 1;
    if (char === ')') depth -= 1;
    if (depth === 0) return index;
    if (char === '\n' && depth === 1) return -1;
  }
  return -1;
}

function shouldRenderAsInlineMath(content: string, before?: string, after?: string) {
  if (!content || content.length > 180) return false;
  if (/\p{Script=Han}{2,}/u.test(content)) return false;
  if (/\\[a-zA-Z]+|[_^=]|\b(?:omega|alpha|beta|gamma|pi|theta|lambda|sum|int|frac|log)\b|[∑∫ππωΩλθ]/i.test(content)) return true;
  if (/^[A-Za-z]\s*\([^)]{1,40}\)$/.test(content)) return true;
  if (/^[A-Za-z]\s*[=<>≤≥]\s*[^，。：:]{1,80}$/.test(content)) return true;
  if (/^[A-Za-z0-9\\+\-*/\s.]+$/.test(content) && /[A-Za-z]/.test(content) && /[0-9+\-*/\\]/.test(content)) return true;
  if (/^[A-Za-z]$/.test(content) && /[：:,，。\s]/.test(after ?? '')) return true;
  if ((before ?? '') === 'O' && /[A-Za-z\\]/.test(content)) return true;
  return false;
}

function repairBrokenSymbolExplanations(value: string) {
  const lines = value.split('\n');
  const repaired: string[] = [];
  let buffer: string[] = [];

  const flush = () => {
    repaired.push(...buffer);
    buffer = [];
  };

  for (const line of lines) {
    buffer.push(line);
    if (!/[：:]/.test(line)) continue;

    if (buffer.length > 1 && buffer.slice(0, -1).every(isTinyMathFragment)) {
      const compactLine = line.trim();
      const colonIndex = compactLine.search(/[：:]/);
      const label = compactLine.slice(0, colonIndex).trim();
      const rest = compactLine.slice(colonIndex);
      if (label && label.length <= 80) {
        repaired.push(`${label}${rest}`);
        buffer = [];
        continue;
      }
    }
    flush();
  }
  flush();
  return repaired.join('\n');
}

function isTinyMathFragment(line: string) {
  const text = line.trim();
  return text.length > 0 && text.length <= 8 && /^[A-Za-z0-9()=+\-*/\\^_.,\sππωΩλθ{}]+$/.test(text);
}
