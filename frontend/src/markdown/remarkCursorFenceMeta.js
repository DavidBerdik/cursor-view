import { visit } from 'unist-util-visit';

const CURSOR_FENCE_METADATA_PATTERN = /^(\d+):(\d+):(.+)$/;

// Reduce a file path to the smallest stable hint Starry Night needs, such as `.py`.
function getHighlightHintFromPath(filePath) {
  if (typeof filePath !== 'string') {
    return null;
  }

  const trimmedPath = filePath.trim();
  if (!trimmedPath) {
    return null;
  }

  const normalizedPath = trimmedPath.replace(/\\/g, '/');
  const lastSegment = normalizedPath.split('/').pop() || normalizedPath;
  const extensionMatch = /\.[^.\\/]+$/.exec(lastSegment);

  if (extensionMatch) {
    return extensionMatch[0].toLowerCase();
  }

  return lastSegment.toLowerCase() || null;
}

// Rebuild Cursor's `start:end:path` fence header when remark has split it at spaces.
function normalizeCursorFenceLanguage(node) {
  if (typeof node.lang !== 'string') {
    return;
  }

  const metadataSource =
    // Windows paths with spaces can be split between `lang` and `meta`.
    typeof node.meta === 'string' && node.meta.trim()
      ? `${node.lang} ${node.meta}`
      : node.lang;
  const metadataMatch = CURSOR_FENCE_METADATA_PATTERN.exec(metadataSource);

  if (!metadataMatch) {
    return;
  }

  node.lang = getHighlightHintFromPath(metadataMatch[3]) || null;
  if (typeof node.meta === 'string') {
    node.meta = null;
  }
}

export default function remarkCursorFenceMeta() {
  // Normalize Cursor-specific fenced code metadata before rehype builds `language-*` classes.
  return function transformer(tree) {
    visit(tree, 'code', (node) => {
      normalizeCursorFenceLanguage(node);

      // Some malformed fences put the code body in `meta`; move it back into `value`.
      if (typeof node.lang === 'string' && typeof node.meta === 'string' && !node.value) {
        node.value = node.meta;
        node.meta = null;
      }
    });
  };
}
