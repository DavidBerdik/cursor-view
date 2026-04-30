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
        const preparedMessages = await Promise.all(
          rawMessages.map(async (message) => {
            const images = Array.isArray(message.images) ? message.images : [];
            if (typeof message.content !== 'string') {
              return { ...message, images };
            }
            const renderedContent = await prepareMarkdownHtml(message.content);
            // Pre-render mermaid diagrams while the loading spinner is still
            // visible so MermaidBlock receives a ready SVG on first paint and
            // there is no flash of raw source text.
            const mermaidSvgs = await prerenderMermaidDiagrams(renderedContent, darkMode);
            // Cache-warm the opposite theme so the user's first dark/light
            // toggle on this chat hits `mermaidRenderCache` for every
            // diagram instead of falling through to the per-block render
            // queue (which would re-run `mermaid.parse` + `mermaid.render`
            // for every diagram serially while the user watches the page
            // re-flow). The in-message sequential `await` (not
            // `Promise.all`) is load-bearing for THIS message's dual-theme
            // pair: `mermaid.initialize` is a singleton, and a parallel
            // pair would race on `theme: dark | default`. Return value is
            // unused -- the side effect we want is the cache fill, not the
            // SVG map. Doubles prerender wall-time on chats with many
            // diagrams; acceptable in the typical case, and could be
            // bounded by a count threshold (e.g. only warm both themes
            // when `< N` diagrams) if it becomes a noticeable load delay.
            //
            // TODO(bug): On a chat with multiple messages and many
            // diagrams, some diagrams may render with the wrong theme on
            // first paint or after the first toggle, because the
            // `Promise.all(rawMessages.map(...))` outer iteration runs N
            // message-level prerenders concurrently while each message's
            // dual-theme pair fires `mermaid.initialize({ theme: ... })`
            // with alternating values. Suspected cause: the in-message
            // sequential `await` only serializes the two prerenders for
            // ONE message; across messages the dual-theme pairs interleave,
            // and once a message's B-pass calls
            // `mermaid.initialize({ theme: !darkMode })` it overwrites the
            // singleton baseline (mermaid's `processAndSetConfigs` calls
            // `reset()` to that baseline at the start of every
            // `mermaid.render`), so any other message's A-pass render that
            // hasn't yet captured its config will pick up the flipped
            // theme and produce a wrong-themed SVG cached under
            // `(source, darkMode)`. Suspected fix: split into two
            // sequential outer passes (one theme per pass), each using
            // `Promise.all` over messages internally so all concurrent
            // prerenders within a pass share one theme. Not regression-
            // pinned because the frontend has no JS test harness, so the
            // invariant would be enforced by manual verification on a
            // diagram-heavy multi-message chat.
            await prerenderMermaidDiagrams(renderedContent, !darkMode);
            return { ...message, renderedContent, mermaidSvgs, images };
          }),
        );
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
  useLayoutEffect(() => {
    if (loading) {
      return;
    }

    const key = `scroll-chat-${sessionId}`;
    const saved = Number(sessionStorage.getItem(key) ?? '0');
    window.scrollTo(0, saved);

    let saveTimer;
    function handleScroll() {
      clearTimeout(saveTimer);
      saveTimer = setTimeout(() => {
        sessionStorage.setItem(key, String(window.scrollY));
      }, 150);
    }

    window.addEventListener('scroll', handleScroll, { passive: true });

    return () => {
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
