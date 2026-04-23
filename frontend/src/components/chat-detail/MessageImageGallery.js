import React from 'react';
import { Box } from '@mui/material';

// Renders a row of image attachments for one message bubble.
//
// The actual bytes live in the chat-index cache and are served by the
// dedicated `GET /api/chat/<session_id>/image/<uuid>` route rather
// than being inlined into the chat-detail JSON payload, so each <img>
// simply points at that URL and the browser handles caching via the
// route's long-lived `Cache-Control: immutable` header. Each image is
// wrapped in an anchor that opens the same URL in a new tab so users
// can view / save the full-size asset; `rel="noopener"` keeps the new
// tab from reaching back into the chat window.
//
// Layout: the gallery is rendered inside `MessageBubble`'s `<Paper>`,
// as a sibling below the markdown Box. The Paper's padding already
// scopes it horizontally, so this component only sets top spacing
// (`mt`) for separation from the text content above. `role` is kept
// on the prop signature purely so the alt text can distinguish user
// attachments from assistant ones; no role-based margin logic here.
//
// All styling uses MUI theme tokens (`borderColor: 'divider'`) per the
// theme-ownership rule -- no hard-coded colors so dark / light mode
// changes flow through automatically.
export default function MessageImageGallery({ sessionId, images, role }) {
  if (!Array.isArray(images) || images.length === 0) {
    return null;
  }
  // Defensive filter: the backend enforces `chat_image.uuid TEXT NOT NULL`
  // so every well-formed payload has a usable uuid, but a future upstream
  // regression (null entry, missing/non-string uuid) would otherwise crash
  // the whole chat view via an "undefined.uuid" dereference in the .map
  // below. Dropping malformed entries lets the rest of the bubble render.
  const safeImages = images.filter(
    (img) => img && typeof img.uuid === 'string' && img.uuid.length > 0
  );
  if (safeImages.length === 0) {
    return null;
  }
  const alt = `Image attached by ${role === 'user' ? 'user' : 'Cursor'}`;
  const encodedSessionId = encodeURIComponent(sessionId);

  return (
    <Box
      sx={{
        display: 'flex',
        flexWrap: 'wrap',
        gap: 1,
        mt: 1.5,
      }}
    >
      {safeImages.map((img) => {
        const src = `/api/chat/${encodedSessionId}/image/${encodeURIComponent(img.uuid)}`;
        return (
          <Box
            key={img.uuid}
            component="a"
            href={src}
            target="_blank"
            rel="noopener"
            sx={{
              display: 'inline-flex',
              border: '1px solid',
              borderColor: 'divider',
              borderRadius: 1,
              overflow: 'hidden',
              maxWidth: 280,
              lineHeight: 0,
            }}
          >
            <Box
              component="img"
              src={src}
              alt={alt}
              loading="lazy"
              sx={{
                display: 'block',
                maxWidth: '100%',
                height: 'auto',
              }}
            />
          </Box>
        );
      })}
    </Box>
  );
}
