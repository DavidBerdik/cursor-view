import React, { useEffect } from 'react';
import { Box, Dialog, IconButton, Typography } from '@mui/material';
import CloseIcon from '@mui/icons-material/Close';
import ChevronLeftIcon from '@mui/icons-material/ChevronLeft';
import ChevronRightIcon from '@mui/icons-material/ChevronRight';

// Per-message image lightbox rendered over MUI's default dimmed
// backdrop. Scope is the images attached to a single chat message --
// the parent `MessageImageGallery` holds the `openIndex` state and
// passes this modal a filtered, well-formed `images` array (A3's
// defensive filter has already run), so this component does not
// need a second guard layer.
//
// UX invariants: Escape dismisses (via MUI `Dialog`'s `onClose`);
// backdrop click dismisses (also via `Dialog`'s built-in behavior);
// the close button in the top-right mirrors Escape; `ArrowLeft` /
// `ArrowRight` on the keyboard navigate prev/next when the message
// has more than one image. Prev/next chevrons render as edge
// overlays on the image when navigation is available, and a
// thumbnail strip along the bottom lets the user jump to any
// attachment in the same message. Single-image messages collapse
// to just the full-size image + close button.
//
// Byte flow unchanged vs. the thumbnail gallery: the `<img src>`
// here points at the same `GET /api/chat/<session_id>/image/<uuid>`
// route, so the browser reuses its already-cached response from
// the thumbnail render -- no second fetch, no new inline-base64
// path into the chat-detail JSON.
//
// All styling uses MUI theme tokens (`bgcolor: 'background.paper'`,
// `color: 'text.primary'`, `borderColor: 'divider'`, `primary.main`)
// so dark / light mode changes flow through automatically.
export default function ImageLightboxModal({
  sessionId,
  images,
  openIndex,
  onClose,
  onNavigate,
}) {
  const isOpen =
    openIndex !== null &&
    Number.isInteger(openIndex) &&
    openIndex >= 0 &&
    openIndex < images.length;
  const multi = images.length > 1;

  useEffect(() => {
    if (!isOpen || !multi) return undefined;
    const handler = (e) => {
      if (e.key === 'ArrowLeft' && openIndex > 0) {
        onNavigate(openIndex - 1);
      } else if (e.key === 'ArrowRight' && openIndex < images.length - 1) {
        onNavigate(openIndex + 1);
      }
    };
    window.addEventListener('keydown', handler);
    return () => window.removeEventListener('keydown', handler);
  }, [isOpen, multi, openIndex, images.length, onNavigate]);

  if (!isOpen) {
    return null;
  }
  const encodedSessionId = encodeURIComponent(sessionId);
  const current = images[openIndex];
  const src = `/api/chat/${encodedSessionId}/image/${encodeURIComponent(current.uuid)}`;

  return (
    <Dialog
      open
      onClose={onClose}
      maxWidth={false}
      PaperProps={{
        // The modal's outer dimensions are fixed relative to the
        // viewport (not the image), so navigating between images of
        // different sizes no longer resizes or jitters the modal.
        // The image inside scales to fit whatever space the flex
        // layout grants it; small images sit in a larger frame and
        // big images cap at the frame edge.
        //
        // The 95vw / 95vh cap leaves a thin strip of backdrop around
        // the Paper so the dimmed background is still visible -- the
        // point being that the user can see the chat content dimmed
        // behind the modal -- while keeping the modal itself close to
        // the viewport edges (Cursor's own modal behaves similarly).
        // The `m: 0.5` override on MUI's default `m: 32px` Paper
        // margin keeps the backdrop strip tight without letting the
        // Paper butt directly against the viewport edge.
        sx: {
          bgcolor: 'background.paper',
          m: 0.5,
          p: 0,
          borderRadius: 2,
          width: '95vw',
          height: '95vh',
          maxWidth: '95vw',
          maxHeight: '95vh',
          display: 'flex',
          flexDirection: 'column',
        },
      }}
      aria-label="Image preview"
    >
      <Box
        sx={{
          p: 2,
          display: 'flex',
          flexDirection: 'column',
          height: '100%',
          minHeight: 0,
          boxSizing: 'border-box',
        }}
      >
        {/* Toolbar row above the image: counter on the left (only when
            there is more than one image to step through), close button
            pinned to the right via `ml: auto`. Laying these out as flex
            siblings of the image -- rather than absolute overlays --
            keeps them on their own horizontal band and avoids ever
            painting a control on top of the image content. */}
        <Box
          sx={{
            display: 'flex',
            alignItems: 'center',
            minHeight: 32,
            mb: 1.5,
            flexShrink: 0,
          }}
        >
          {multi && (
            <Typography
              variant="body2"
              sx={{
                color: 'text.secondary',
                fontVariantNumeric: 'tabular-nums',
              }}
            >
              {openIndex + 1}/{images.length}
            </Typography>
          )}
          <IconButton
            aria-label="Close"
            onClick={onClose}
            size="small"
            sx={{ ml: 'auto', color: 'text.primary' }}
          >
            <CloseIcon />
          </IconButton>
        </Box>

        {/* Image row: takes `flex: 1` so the image area grows to fill
            whatever vertical space the fixed-dimension Paper has left
            between the toolbar and the thumbnail strip. The prev/next
            chevrons live in the thumbnail strip below (next to the
            thumbnails) rather than here, so this row contains only
            the full-size image and keeps the content surface clean. */}
        <Box
          sx={{
            flex: 1,
            minHeight: 0,
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
          }}
        >
          <Box
            component="img"
            src={src}
            alt={`Image ${openIndex + 1} of ${images.length}`}
            sx={{
              flex: '0 1 auto',
              minWidth: 0,
              minHeight: 0,
              maxWidth: '100%',
              maxHeight: '100%',
              display: 'block',
              objectFit: 'contain',
            }}
          />
        </Box>

        {/* Thumbnail strip with prev/next chevrons as flex siblings on
            either side. Chevrons disable at edges (grayed, non-
            interactive) rather than disappear so the thumbnail block
            does not jitter horizontally when the user reaches the
            first or last attachment. All navigation UI lives in this
            band, leaving the image area above free of controls. */}
        {multi && (
          <Box
            sx={{
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'center',
              gap: 1,
              mt: 2,
              flexShrink: 0,
            }}
          >
            <IconButton
              aria-label="Previous image"
              onClick={() => onNavigate(openIndex - 1)}
              disabled={openIndex === 0}
              sx={{ color: 'text.primary', flexShrink: 0 }}
            >
              <ChevronLeftIcon />
            </IconButton>
            <Box
              sx={{
                display: 'flex',
                flexWrap: 'wrap',
                gap: 1,
                justifyContent: 'center',
              }}
            >
              {images.map((img, i) => {
                const thumbSrc = `/api/chat/${encodedSessionId}/image/${encodeURIComponent(img.uuid)}`;
                const isActive = i === openIndex;
                return (
                  <Box
                    key={img.uuid}
                    component="button"
                    type="button"
                    onClick={() => onNavigate(i)}
                    aria-label={`Show image ${i + 1} of ${images.length}`}
                    aria-current={isActive ? 'true' : undefined}
                    sx={{
                      cursor: 'pointer',
                      p: 0,
                      border: '2px solid',
                      borderColor: isActive ? 'primary.main' : 'divider',
                      borderRadius: 1,
                      overflow: 'hidden',
                      backgroundColor: 'transparent',
                      lineHeight: 0,
                      width: 56,
                      height: 56,
                    }}
                  >
                    <Box
                      component="img"
                      src={thumbSrc}
                      alt=""
                      loading="lazy"
                      sx={{
                        width: '100%',
                        height: '100%',
                        objectFit: 'cover',
                        display: 'block',
                      }}
                    />
                  </Box>
                );
              })}
            </Box>
            <IconButton
              aria-label="Next image"
              onClick={() => onNavigate(openIndex + 1)}
              disabled={openIndex === images.length - 1}
              sx={{ color: 'text.primary', flexShrink: 0 }}
            >
              <ChevronRightIcon />
            </IconButton>
          </Box>
        )}
      </Box>
    </Dialog>
  );
}
