import React, { useContext } from 'react';
import { Box, alpha } from '@mui/material';
import parse from 'html-react-parser';
import { ThemeModeContext } from '../contexts/ThemeModeContext';
import MermaidBlock from './MermaidBlock';
import { useMermaid } from '../hooks/useMermaid';

function getCodeBlockBackground(colors, role, darkMode) {
  if (role === 'user') {
    return alpha(colors.primary.main, darkMode ? 0.16 : 0.07);
  }

  return alpha(colors.highlightColor, darkMode ? 0.2 : 0.1);
}

// Returns true when an html-dom-parser element node is a mermaid code block,
// i.e. <code class="language-mermaid"> (possibly with additional classes).
function isMermaidCodeNode(node) {
  if (node.type !== 'tag' || node.name !== 'code') {
    return false;
  }
  const classes = (node.attribs?.class ?? '').split(/\s+/);
  return classes.includes('language-mermaid');
}

// Extracts the text content from an html-dom-parser element's children.
function textContent(node) {
  return (node.children ?? [])
    .filter((c) => c.type === 'text')
    .map((c) => c.data)
    .join('');
}

export default function MessageMarkdown({ html, colors, role, mermaidSvgs }) {
  const { darkMode } = useContext(ThemeModeContext);
  // Bootstraps the mermaid singleton and keeps its theme in sync with
  // dark/light mode. MermaidBlock also calls mermaid.initialize before
  // each render; this hook is the global owner of startOnLoad:false.
  useMermaid();

  const codeBlockBackground = getCodeBlockBackground(colors, role, darkMode);

  // Replace <pre><code class="language-mermaid">…</code></pre> nodes
  // produced by rehype-stringify with a MermaidBlock React component.
  // We intercept at the <pre> level so the wrapper element is removed and
  // MermaidBlock's own block-level Box takes its place cleanly.
  // All other nodes fall through to the default html-react-parser conversion.
  function replaceNode(node) {
    if (node.type !== 'tag' || node.name !== 'pre') {
      return undefined;
    }
    const codeChild = (node.children ?? []).find(
      (c) => c.type === 'tag' && isMermaidCodeNode(c),
    );
    if (!codeChild) {
      return undefined;
    }
    const source = textContent(codeChild);
    const prerender = mermaidSvgs instanceof Map ? mermaidSvgs.get(source) : undefined;
    return (
      <MermaidBlock
        source={source}
        initialSvg={prerender?.svg ?? undefined}
        initialError={prerender?.error ?? undefined}
        initialDarkMode={prerender?.darkMode}
      />
    );
  }

  const parsedContent = parse(html || '', { replace: replaceNode });

  return (
    <Box
      className={`chat-markdown ${darkMode ? 'chat-markdown-dark' : 'chat-markdown-light'}`}
      sx={{
        '& pre': {
          maxWidth: '100%',
          overflowX: 'auto',
          backgroundColor: codeBlockBackground,
          color: colors.text.primary,
          borderRadius: 1,
          p: 2,
          m: 0,
        },
        '& pre code': {
          display: 'block',
          fontSize: 'inherit',
          backgroundColor: 'transparent',
          color: 'inherit',
          p: 0,
          borderRadius: 0,
        },
        '& code': {
          fontFamily: 'source-code-pro, Menlo, Monaco, Consolas, "Courier New", monospace',
        },
      }}
    >
      <Box
        sx={{
          '& :not(pre) > code': {
            display: 'inline',
            fontSize: '0.85em',
            backgroundColor: getCodeBlockBackground(colors, role, darkMode),
            color: colors.text.primary,
            borderRadius: 0.5,
            px: 0.8,
            py: 0.2,
            verticalAlign: 'baseline',
          },
        }}
      >
        {parsedContent}
      </Box>
    </Box>
  );
}
