import { visit } from 'unist-util-visit';

const CURSOR_FENCE_METADATA_PATTERN = /^(\d+):(\d+):(.+)$/;

export default function remarkCursorFenceMeta() {
  return function transformer(tree) {
    visit(tree, 'code', (node) => {
      if (typeof node.lang === 'string') {
        const metadataMatch = CURSOR_FENCE_METADATA_PATTERN.exec(node.lang);
        if (metadataMatch) {
          node.lang = metadataMatch[3];
        }
      }

      if (typeof node.lang === 'string' && typeof node.meta === 'string' && !node.value) {
        node.value = node.meta;
        node.meta = null;
      }
    });
  };
}
