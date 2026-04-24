import React, { useCallback, useState } from 'react';
import { Box } from '@mui/material';
import ImageLightboxModal from './ImageLightboxModal';

// Renders a row of clickable image-attachment thumbnails for one
// chat message. Each thumbnail is a `<button>` whose click opens
// the sibling `ImageLightboxModal` at the corresponding index, so
// users view attachments in place rather than being yanked out to
// a new browser tab. This parity with Cursor's own chat UI is the
// whole point of A10; HTML exports continue to use the anchor /
// new-tab pattern from A9 because exported files have no React
// runtime to host a modal.
//
// Image bytes live in the chat-index cache and are served by the
// dedicated `GET /api/chat/<session_id>/image/<uuid>` route rather
// than being inlined into the chat-detail JSON payload, so each
// thumbnail and the modal's full-size `<img>` both hit the same
// URL -- the browser's cache satisfies the modal load from the
// already-fetched thumbnail bytes. The route's long-lived
// `Cache-Control: immutable` header keeps that working across
// re-renders.
//
// Layout: the gallery is rendered inside `MessageBubble`'s
// `<Paper>`, as a sibling below the markdown Box. The Paper's
// padding already scopes it horizontally, so this component only
// sets top spacing (`mt`) for separation from the text content
// above. `role` is kept on the prop signature purely so the alt
// text can distinguish user attachments from assistant ones.
//
// All styling uses MUI theme tokens (`borderColor: 'divider'`) per
// the theme-ownership rule -- no hard-coded colors so dark / light
// mode changes flow through automatically.
export default function MessageImageGallery({ sessionId, images, role }) {
  const [openIndex, setOpenIndex] = useState(null);

  // Stable callbacks so the modal's keydown `useEffect` does not
  // re-register its listener on every parent re-render, per
  // `frontend-hooks.mdc`'s "Stable callback references" clause.
  const handleClose = useCallback(() => setOpenIndex(null), []);
  const handleNavigate = useCallback((i) => setOpenIndex(i), []);

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
    <>
      <Box
        sx={{
          display: 'flex',
          flexWrap: 'wrap',
          gap: 1,
          mt: 1.5,
        }}
      >
        {safeImages.map((img, i) => {
          const src = `/api/chat/${encodedSessionId}/image/${encodeURIComponent(img.uuid)}`;
          return (
            <Box
              key={img.uuid}
              component="button"
              type="button"
              onClick={() => setOpenIndex(i)}
              aria-label={alt}
              sx={{
                display: 'inline-flex',
                cursor: 'pointer',
                p: 0,
                border: '1px solid',
                borderColor: 'divider',
                borderRadius: 1,
                overflow: 'hidden',
                maxWidth: 280,
                backgroundColor: 'transparent',
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
      <ImageLightboxModal
        sessionId={sessionId}
        images={safeImages}
        openIndex={openIndex}
        onClose={handleClose}
        onNavigate={handleNavigate}
      />
    </>
  );
}
