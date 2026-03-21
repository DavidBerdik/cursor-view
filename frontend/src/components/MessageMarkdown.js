import React, { useContext } from 'react';
import ReactMarkdown, { MarkdownHooks } from 'react-markdown';
import remarkGfm from 'remark-gfm';
import rehypeStarryNight from 'rehype-starry-night';
import { Box, alpha } from '@mui/material';
import { ThemeModeContext } from '../App';
import remarkCursorFenceMeta from '../markdown/remarkCursorFenceMeta';

function getCodeBlockBackground(colors, role, darkMode) {
  if (role === 'user') {
    return alpha(colors.primary.main, darkMode ? 0.16 : 0.07);
  }

  return alpha(colors.highlightColor, darkMode ? 0.2 : 0.1);
}

function renderInlineCode(children, colors, role, darkMode, props) {
  return (
    <Box
      component="code"
      sx={{
        display: 'inline',
        fontSize: '0.85em',
        backgroundColor: getCodeBlockBackground(colors, role, darkMode),
        color: colors.text.primary,
        borderRadius: 0.5,
        px: 0.8,
        py: 0.2,
        verticalAlign: 'baseline',
      }}
      {...props}
    >
      {children}
    </Box>
  );
}

export default function MessageMarkdown({ content, colors, role }) {
  const { darkMode } = useContext(ThemeModeContext);
  const codeBlockBackground = getCodeBlockBackground(colors, role, darkMode);

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
      <MarkdownHooks
        fallback={
          <ReactMarkdown remarkPlugins={[remarkGfm]}>
            {content}
          </ReactMarkdown>
        }
        remarkPlugins={[remarkGfm, remarkCursorFenceMeta]}
        rehypePlugins={[[rehypeStarryNight, { allowMissingScopes: true }]]}
        components={{
          code({ className, children, ...props }) {
            if (className) {
              return (
                <code className={className} {...props}>
                  {children}
                </code>
              );
            }

            return renderInlineCode(children, colors, role, darkMode, props);
          },
        }}
      >
        {content}
      </MarkdownHooks>
    </Box>
  );
}
