import React from 'react';
import { Avatar, Box, Paper, Typography } from '@mui/material';
import PersonIcon from '@mui/icons-material/Person';
import SmartToyIcon from '@mui/icons-material/SmartToy';
import MessageMarkdown from '../MessageMarkdown';
import MessageImageGallery from './MessageImageGallery';
import { PALETTE_TRANSITION } from '../../theme/transitions';

// One user/assistant bubble: avatar + role label in the header row,
// then a Paper with the pre-rendered markdown HTML (done upstream in
// ChatDetail's effect via `prepareMarkdownHtml`). The Box around
// MessageMarkdown owns the in-chat styling for links, tables, lists,
// and images so the markdown output blends with the chat theme.
// Image attachments render inside the same Paper, as a sibling below
// the markdown Box, so the bubble visually contains its attachments
// and matches the Markdown / HTML exports (both of which keep images
// inside the message block). The Paper's own padding scopes the
// gallery horizontally, which is why the gallery no longer sets its
// own role-based asymmetric margins.
//
// `index` is the message's position in the parent `MessageList` and
// gets attached as `data-msg-idx` on the outermost `<Box>` so
// `ChatDetail`'s anchor-based scroll restoration can locate the
// bubble in the post-load layout. The data attribute is the load-
// bearing handle: `MermaidBlock`'s `content-visibility: auto`
// placeholder height (400px) does not match the actual diagram
// height after materialization, so a raw `window.scrollY` save/
// restore drifts on every refresh of a diagram-heavy chat. Querying
// by `data-msg-idx` lets the restore recompute against the current
// layout's `offsetTop` instead.
export default function MessageBubble({ sessionId, message, index }) {
  const isUser = message.role === 'user';
  // Accent color picks the highlight token for user bubbles and the
  // secondary palette for assistant bubbles. Both are CSS-var
  // references so the avatar background, border-left, and inline-link
  // color all swap with the active scheme without re-rendering.
  const accent = isUser
    ? 'var(--mui-palette-highlight-main)'
    : 'var(--mui-palette-secondary-main)';
  const images = Array.isArray(message.images) ? message.images : [];

  return (
    <Box data-msg-idx={index} sx={{ mb: 3.5 }}>
      <Box sx={{ display: 'flex', alignItems: 'center', mb: 1.5 }}>
        <Avatar
          sx={{
            bgcolor: accent,
            width: 32,
            height: 32,
            mr: 1.5,
            boxShadow: '0 2px 4px rgba(0,0,0,0.1)',
          }}
        >
          {isUser ? <PersonIcon /> : <SmartToyIcon />}
        </Avatar>
        <Typography variant="subtitle1" fontWeight="600">
          {isUser ? 'User' : 'Cursor'}
        </Typography>
      </Box>

      <Paper
        elevation={1}
        sx={{
          p: 2.5,
          ml: isUser ? 0 : 5,
          mr: isUser ? 5 : 0,
          backgroundColor: 'rgba(var(--mui-palette-highlight-mainChannel) / 0.04)',
          borderLeft: '4px solid',
          borderColor: accent,
          borderRadius: 2,
        }}
      >
        <Box
          sx={{
            transition: PALETTE_TRANSITION,
            '& img': { maxWidth: '100%' },
            '& ul, & ol': { pl: 3 },
            '& a': {
              color: accent,
              textDecoration: 'none',
              '&:hover': { textDecoration: 'none' },
            },
            '& table': {
              width: '100%',
              borderCollapse: 'collapse',
              my: 2,
              fontSize: '0.9em',
            },
            '& th, & td': {
              border: '1px solid',
              borderColor: 'divider',
              px: 1.5,
              py: 1,
              textAlign: 'left',
            },
            // CSS `transition` does not cascade through descendant
            // selectors, so the parent transition above does not reach
            // `<th>` / `<tr>`. The two rules below own
            // `backgroundColor: rgba(var(--mui-palette-highlight-mainChannel) / N)` tints
            // that flip between dark and light via CSS variables (no
            // React re-render needed), but they still need their own
            // `transition` so the alpha-tinted background fades rather
            // than flashes when the scheme attribute flips and the
            // browser recomputes styles.
            '& th': {
              fontWeight: 600,
              backgroundColor: 'rgba(var(--mui-palette-highlight-mainChannel) / 0.08)',
              transition: PALETTE_TRANSITION,
            },
            '& tr:nth-of-type(even)': {
              backgroundColor: 'rgba(var(--mui-palette-highlight-mainChannel) / 0.03)',
              transition: PALETTE_TRANSITION,
            },
          }}
        >
          {typeof message.renderedContent === 'string' ? (
            <MessageMarkdown
              html={message.renderedContent}
              role={message.role}
              mermaidSvgs={message.mermaidSvgs}
            />
          ) : (
            <Typography>Content unavailable</Typography>
          )}
        </Box>
        {images.length > 0 && (
          <MessageImageGallery
            sessionId={sessionId}
            images={images}
            role={message.role}
          />
        )}
      </Paper>
    </Box>
  );
}
