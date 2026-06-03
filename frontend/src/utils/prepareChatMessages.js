import { prepareMarkdownHtml } from '../markdown/prepareMarkdownHtml';
import { prerenderMermaidDiagrams } from './prerenderMermaidDiagrams';

// Shared fetch-result-to-render-state pipeline for a chat's messages,
// consumed by both `ChatDetail` (cache-backed `/api/chat/:id`) and
// `ChatViewer` (the desktop opened-file `/api/viewer/opened` route).
// Centralized here so the delicate three-phase mermaid ordering below
// lives in exactly one place -- duplicating it across the two pages
// would reintroduce the cross-message singleton race retired in
// known-bugs.mdc.
//
// Three sequential outer phases (markdown prep, theme A prerender,
// theme B prerender) instead of one fused per-message closure. The
// dual-theme prerender pair MUST NOT be nested inside a `Promise.all`
// over messages: every call to `prerenderMermaidDiagrams` flips the
// global `mermaid.initialize({ theme: ... })` setting and then runs its
// own internal `Promise.all` over the diagrams in one message, so two
// interleaved per-message pairs would race on the singleton -- a B-pass
// call from one message overwrites the baseline mid-flight, and any
// other message's A-pass render that has not yet captured its config
// picks up the flipped theme via mermaid's `processAndSetConfigs`
// `reset()`-to-baseline at the start of every `mermaid.render`,
// producing a wrong-themed SVG cached under `(source, darkMode)`. The
// fix is to give each `prerenderMermaidDiagrams` call uncontested
// ownership of the singleton for its full lifetime by running all
// messages' active-theme prerenders together, awaiting completion, then
// running all messages' opposite-theme prerenders together. See
// `mermaid-rendering.mdc` "Render cache and queue" ->
// `prerenderMermaidDiagrams` writer for the singleton contract this
// honors.
export async function prepareChatMessages(rawMessages, darkMode) {
  const messages = Array.isArray(rawMessages) ? rawMessages : [];

  const messagesWithHtml = await Promise.all(
    messages.map(async (message) => {
      const images = Array.isArray(message.images) ? message.images : [];
      if (typeof message.content !== 'string') {
        return { ...message, images };
      }
      const renderedContent = await prepareMarkdownHtml(message.content);
      return { ...message, renderedContent, images };
    }),
  );

  const mermaidSvgsByMessage = await Promise.all(
    messagesWithHtml.map((m) =>
      typeof m.renderedContent === 'string'
        ? prerenderMermaidDiagrams(m.renderedContent, darkMode)
        : Promise.resolve(null),
    ),
  );

  // Opposite-theme cache-warm pass. Return value is unused; the side
  // effect we want is the `mermaidRenderCache` fill for
  // `(source, !darkMode)` so the user's first dark/light toggle hits
  // the cache for every diagram instead of falling through to the
  // per-block render queue.
  await Promise.all(
    messagesWithHtml.map((m) =>
      typeof m.renderedContent === 'string'
        ? prerenderMermaidDiagrams(m.renderedContent, !darkMode)
        : Promise.resolve(null),
    ),
  );

  return messagesWithHtml.map((m, idx) => {
    const mermaidSvgs = mermaidSvgsByMessage[idx];
    if (mermaidSvgs === null) {
      return m;
    }
    return { ...m, mermaidSvgs };
  });
}
