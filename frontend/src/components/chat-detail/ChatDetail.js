import React, { startTransition, useContext, useEffect, useLayoutEffect, useMemo, useState } from 'react';
import { useParams, Link } from 'react-router-dom';
import axios from 'axios';
import {
  alpha,
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
import { ColorContext } from '../../contexts/ColorContext';
import { ThemeModeContext } from '../../contexts/ThemeModeContext';
import { useExportFlow } from '../../hooks/useExportFlow';
import ExportFormatDialog from '../export/ExportFormatDialog';
import ExportWarningDialog from '../export/ExportWarningDialog';
import ChatMetaPanel from './ChatMetaPanel';
import MessageList from './MessageList';

const ChatDetail = () => {
  const colors = useContext(ColorContext);
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
        <CircularProgress sx={{ color: colors.highlightColor }} />
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
              backgroundColor: alpha(colors.highlightColor, 0.8),
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
              backgroundColor: alpha(colors.highlightColor, 0.8),
            },
          }}
        >
          Export
        </Button>
      </Box>

      <ChatMetaPanel chat={chat} />

      <Typography variant="h5" gutterBottom fontWeight="600" sx={{ mt: 4, mb: 3 }}>
        Conversation History
      </Typography>

      <MessageList sessionId={sessionId} messages={messages} />
    </Container>
  );
};

export default ChatDetail;
