import rehypeStringify from 'rehype-stringify';
import rehypeStarryNight from 'rehype-starry-night';
import remarkGfm from 'remark-gfm';
import remarkParse from 'remark-parse';
import remarkRehype from 'remark-rehype';
import { unified } from 'unified';
import remarkCursorFenceMeta from './remarkCursorFenceMeta';

const markdownProcessor = unified()
  .use(remarkParse)
  .use(remarkGfm)
  .use(remarkCursorFenceMeta)
  .use(remarkRehype)
  .use(rehypeStarryNight, { allowMissingScopes: true })
  .use(rehypeStringify);

const markdownHtmlCache = new Map();

export async function prepareMarkdownHtml(content) {
  const markdown = typeof content === 'string' ? content : '';

  if (markdownHtmlCache.has(markdown)) {
    return markdownHtmlCache.get(markdown);
  }

  const pendingHtml = markdownProcessor
    .process(markdown)
    .then((file) => String(file))
    .catch((error) => {
      markdownHtmlCache.delete(markdown);
      throw error;
    });

  markdownHtmlCache.set(markdown, pendingHtml);
  return pendingHtml;
}
