import React, { startTransition, useContext, useEffect, useLayoutEffect, useMemo, useState } from 'react';
import { useParams, Link } from 'react-router-dom';
import axios from 'axios';
import {
  Box,
  Button,
  CircularProgress,
  Container,
  Typography,
} from '@mui/material';
import ArrowBackIcon from '@mui/icons-material/ArrowBack';
import FileDownloadIcon from '@mui/icons-material/FileDownload';
import { prepareMarkdownHtml } from '../../markdown/prepareMarkdownHtml';
import { prerenderMermaidDiagrams } from '../../utils/prerenderMermaidDiagrams';
import { ThemeModeContext } from '../../contexts/ThemeModeContext';
import { useExportFlow } from '../../hooks/useExportFlow';
import ExportFormatDialog from '../export/ExportFormatDialog';
import ExportWarningDialog from '../export/ExportWarningDialog';
import ChatMetaPanel from './ChatMetaPanel';
import MessageList from './MessageList';

const ChatDetail = () => {
  const { darkMode } = useContext(ThemeModeContext);
  const { sessionId } = useParams();
  const [chat, setChat] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const {
    format,
    setFormat,
    dontShow,
    setDontShow,
    formatDialogOpen,
    warningDialogOpen,
    requestExport,
    handleFormatConfirm,
    handleWarningConfirm,
  } = useExportFlow({ darkMode });

  useEffect(() => {
    let cancelled = false;

    setLoading(true);
    setError(null);

    axios
      .get(`/api/chat/${sessionId}`)
      .then(async (response) => {
        if (cancelled) {
          return;
        }
        const fetchedChat = response.data;
        const rawMessages = Array.isArray(fetchedChat.messages) ? fetchedChat.messages : [];

        // Three sequential outer phases (markdown prep, theme A
        // prerender, theme B prerender) instead of one fused
        // per-message closure. The dual-theme prerender pair MUST
        // NOT be nested inside a `Promise.all` over messages: every
        // call to `prerenderMermaidDiagrams` flips the global
        // `mermaid.initialize({ theme: ... })` setting and then
        // runs its own internal `Promise.all` over the diagrams in
        // one message, so two interleaved per-message pairs would
        // race on the singleton -- a B-pass call from one message
        // overwrites the baseline mid-flight, and any other
        // message's A-pass render that has not yet captured its
        // config picks up the flipped theme via mermaid's
        // `processAndSetConfigs` `reset()`-to-baseline at the
        // start of every `mermaid.render`, producing a wrong-
        // themed SVG cached under `(source, darkMode)`. The fix
        // is to give each `prerenderMermaidDiagrams` call uncontested
        // ownership of the singleton for its full lifetime by
        // running all messages' active-theme prerenders together,
        // awaiting completion, then running all messages' opposite-
        // theme prerenders together. Phase A also moves out of
        // the per-message closure so its `Promise.all` can fan out
        // markdown work without any mermaid state at all. See
        // `mermaid-rendering.mdc` "Render cache and queue" →
        // `prerenderMermaidDiagrams` writer for the singleton
        // contract this honors.

        const messagesWithHtml = await Promise.all(
          rawMessages.map(async (message) => {
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

        // Opposite-theme cache-warm pass. Return value is unused;
        // the side effect we want is the `mermaidRenderCache` fill
        // for `(source, !darkMode)` so the user's first dark/light
        // toggle hits the cache for every diagram instead of
        // falling through to the per-block render queue.
        await Promise.all(
          messagesWithHtml.map((m) =>
            typeof m.renderedContent === 'string'
              ? prerenderMermaidDiagrams(m.renderedContent, !darkMode)
              : Promise.resolve(null),
          ),
        );

        const preparedMessages = messagesWithHtml.map((m, idx) => {
          const mermaidSvgs = mermaidSvgsByMessage[idx];
          if (mermaidSvgs === null) {
            return m;
          }
          return { ...m, mermaidSvgs };
        });

        if (cancelled) {
          return;
        }
        startTransition(() => {
          setChat({
            ...fetchedChat,
            messages: preparedMessages,
          });
          setLoading(false);
        });
      })
      .catch((err) => {
        if (cancelled) {
          return;
        }
        setError(err.message);
        setLoading(false);
      });

    return () => {
      cancelled = true;
    };
  }, [sessionId]);

  // Restore the saved scroll position and begin tracking it for future
  // refreshes. useLayoutEffect fires after React commits the DOM but before
  // the browser paints, so scrollTo executes before the first frame is
  // drawn and the user never sees a flash at position 0. A requestAnimationFrame
  // is not needed here because useLayoutEffect already guarantees the content
  // DOM (and its full height) is in place when the callback runs.
  //
  // Key is per-session so navigating to a different chat starts at the top.
  // window.history.scrollRestoration is set to 'manual' in App.js so the
  // browser's own restore attempt cannot fire during the spinner and clobber
  // the position we set here.
  //
  // Save / restore is anchor-based: instead of persisting a raw
  // `window.scrollY`, we record the topmost in-viewport message bubble's
  // index plus the user's vertical offset within it (`{ msgIdx, offset }`
  // JSON in `sessionStorage`). At restore time we recompute scrollY from
  // the anchor's current `offsetTop` plus the saved offset. This is
  // robust to layout changes between save and restore -- specifically,
  // `MermaidBlock`'s `contentVisibility: 'auto'` + `containIntrinsicSize:
  // '0 400px'` pair gives every off-screen mermaid block a 400px placeholder
  // height that does not match the actual rendered diagram height. A raw
  // scrollY save/restore drifts because every materialized-then-de-materialized
  // mermaid block above the viewport changes total page height between save
  // (some blocks materialized) and restore (all off-screen blocks at the
  // 400px placeholder). Anchoring to a specific message absorbs that drift:
  // any size delta in mermaid blocks above the anchor moves the anchor's
  // `offsetTop` by exactly the same amount, so `offsetTop + offset` lands
  // on the same visual position within the anchor.
  //
  // Two fallbacks: a legacy plain-number entry (existing user
  // `sessionStorage` from before this change) restores via the original
  // `Number(raw)` path; a JSON entry whose `msgIdx` no longer exists in
  // the DOM (e.g. a chat that lost messages) restores to the top, which
  // is safer than scrolling to a stale absolute scrollY that no longer
  // corresponds to anything in the new layout.
  useLayoutEffect(() => {
    if (loading) {
      return;
    }

    const key = `scroll-chat-${sessionId}`;
    const raw = sessionStorage.getItem(key);
    let targetY = 0;
    let stabilizationData = null;
    if (raw !== null) {
      try {
        const parsed = JSON.parse(raw);
        if (typeof parsed === 'number') {
          targetY = parsed;
        } else if (parsed && typeof parsed === 'object' && typeof parsed.msgIdx === 'number') {
          const anchorEl = document.querySelector(`[data-msg-idx="${parsed.msgIdx}"]`);
          if (anchorEl !== null) {
            const offset = typeof parsed.offset === 'number' ? parsed.offset : 0;
            targetY = anchorEl.offsetTop + offset;
            stabilizationData = { msgIdx: parsed.msgIdx, offset };
          }
        }
      } catch {
        targetY = Number(raw) || 0;
      }
    }
    window.scrollTo(0, targetY);

    // `content-visibility: auto` on every off-screen `MermaidBlock`
    // skips layout/paint at the 400px placeholder until the block
    // enters the viewport buffer; the `scrollTo` above causes the
    // browser to re-evaluate that, materializing blocks now in or
    // near the new viewport on the next paint and shifting
    // `anchor.offsetTop` while `scrollY` stays put. Chase that shift
    // via rAF: each iteration re-reads the anchor's `offsetTop` and
    // re-scrolls if it differs from the current `scrollY` by more
    // than the 1-px tolerance (which prevents a no-op `scrollTo`
    // from re-triggering layout work). 5-frame cap is a safety net
    // against a pathological materialization cascade; in practice
    // 2-3 frames are enough. Skipped entirely for the legacy plain-
    // number fallback and the no-saved-entry / anchor-missing paths
    // because there is no anchor to stabilize against.
    let stabilizationRafId = null;
    if (stabilizationData !== null) {
      let frame = 0;
      const MAX_STABILIZATION_FRAMES = 5;
      const tryStabilize = () => {
        stabilizationRafId = null;
        if (frame >= MAX_STABILIZATION_FRAMES) {
          return;
        }
        frame += 1;
        const anchorEl = document.querySelector(
          `[data-msg-idx="${stabilizationData.msgIdx}"]`,
        );
        if (anchorEl === null) {
          return;
        }
        const newTargetY = anchorEl.offsetTop + stabilizationData.offset;
        if (Math.abs(newTargetY - window.scrollY) > 1) {
          window.scrollTo(0, newTargetY);
        }
        stabilizationRafId = requestAnimationFrame(tryStabilize);
      };
      stabilizationRafId = requestAnimationFrame(tryStabilize);
    }

    let saveTimer;
    function handleScroll() {
      clearTimeout(saveTimer);
      saveTimer = setTimeout(() => {
        // Topmost in-viewport bubble: the first `[data-msg-idx]`
        // whose bottom edge is below the viewport top. If no bubble
        // intersects the viewport (very short chat scrolled past end,
        // empty chat), persist the raw scrollY so the legacy restore
        // path picks it up next load.
        const els = document.querySelectorAll('[data-msg-idx]');
        let anchor = null;
        for (const el of els) {
          if (el.getBoundingClientRect().bottom > 0) {
            anchor = el;
            break;
          }
        }
        if (anchor === null) {
          sessionStorage.setItem(key, String(window.scrollY));
          return;
        }
        const msgIdx = Number(anchor.dataset.msgIdx);
        const offset = window.scrollY - anchor.offsetTop;
        sessionStorage.setItem(key, JSON.stringify({ msgIdx, offset }));
      }, 150);
    }

    window.addEventListener('scroll', handleScroll, { passive: true });

    return () => {
      if (stabilizationRafId !== null) {
        cancelAnimationFrame(stabilizationRafId);
      }
      clearTimeout(saveTimer);
      window.removeEventListener('scroll', handleScroll);
    };
  }, [loading, sessionId]);

  const messages = useMemo(
    () => (Array.isArray(chat?.messages) ? chat.messages : []),
    [chat?.messages],
  );

  if (loading) {
    return (
      <Container sx={{ display: 'flex', justifyContent: 'center', alignItems: 'center', height: '70vh' }}>
        <CircularProgress sx={{ color: 'var(--mui-palette-highlight-main)' }} />
      </Container>
    );
  }

  if (error) {
    return (
      <Container>
        <Typography variant="h5" color="error">
          Error: {error}
        </Typography>
      </Container>
    );
  }

  if (!chat) {
    return (
      <Container>
        <Typography variant="h5">
          Chat not found
        </Typography>
      </Container>
    );
  }

  return (
    <Container sx={{ mb: 6 }}>
      <ExportFormatDialog
        open={formatDialogOpen}
        format={format}
        onFormatChange={setFormat}
        onClose={handleFormatConfirm}
      />

      <ExportWarningDialog
        open={warningDialogOpen}
        dontShow={dontShow}
        onDontShowChange={setDontShow}
        onClose={handleWarningConfirm}
      />

      <Box sx={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', mb: 3, mt: 2, gap: 2 }}>
        <Button
          component={Link}
          to="/"
          startIcon={<ArrowBackIcon />}
          variant="contained"
          color="highlight"
          sx={{
            borderRadius: 2,
            color: 'white',
            '&:hover': {
              backgroundColor: 'rgba(var(--mui-palette-highlight-mainChannel) / 0.8)',
            },
          }}
        >
          Back to all chats
        </Button>

        <Button
          onClick={() => requestExport(sessionId)}
          startIcon={<FileDownloadIcon />}
          variant="contained"
          color="highlight"
          sx={{
            borderRadius: 2,
            color: 'white',
            '&:hover': {
              backgroundColor: 'rgba(var(--mui-palette-highlight-mainChannel) / 0.8)',
            },
          }}
        >
          Export
        </Button>
      </Box>

      {chat.title && (
        <Typography variant="h4" fontWeight={700} sx={{ mb: 2 }}>
          {chat.title}
        </Typography>
      )}

      <ChatMetaPanel chat={chat} />

      <Typography variant="h5" gutterBottom fontWeight="600" sx={{ mt: 4, mb: 3 }}>
        Conversation History
      </Typography>

      <MessageList sessionId={sessionId} messages={messages} />
    </Container>
  );
};

export default ChatDetail;
