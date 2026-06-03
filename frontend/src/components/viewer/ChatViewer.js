import React, { startTransition, useContext, useEffect, useMemo, useState } from 'react';
import { Link } from 'react-router-dom';
import axios from 'axios';
import {
  Box,
  Button,
  CircularProgress,
  Container,
  Typography,
} from '@mui/material';
import ArrowBackIcon from '@mui/icons-material/ArrowBack';
import { prepareChatMessages } from '../../utils/prepareChatMessages';
import { ThemeModeContext } from '../../contexts/ThemeModeContext';
import ChatMetaPanel from '../chat-detail/ChatMetaPanel';
import MessageList from '../chat-detail/MessageList';

// Single-chat viewer for a file opened from disk (the macOS file-type
// association or `cursor-view-desktop <file>`). Unlike ChatDetail it
// fetches the desktop-only `/api/viewer/opened` route -- the chat is the
// exported JSON file the launcher read at startup, NOT a row in the
// chat-index cache -- so there is no sessionId, no export button (the
// export route hits the cache, which need not contain this chat), and no
// scroll-anchor persistence (single, transient page). Rendering reuses
// the chat-detail MessageList/MessageBubble tree; images render from the
// inlined `data:` URIs in the export via the shared `imageSrc` helper.
const ChatViewer = () => {
  const { darkMode } = useContext(ThemeModeContext);
  const [chat, setChat] = useState(null);
  const [loading, setLoading] = useState(true);
  // `notFound` is the expected empty state (no file opened, or a file
  // that failed to parse -> the route 404s); `error` is an unexpected
  // transport failure. They render differently so a launched-without-a-
  // file window does not look broken.
  const [notFound, setNotFound] = useState(false);
  const [error, setError] = useState(null);

  useEffect(() => {
    let cancelled = false;

    setLoading(true);
    setNotFound(false);
    setError(null);

    axios
      .get('/api/viewer/opened')
      .then(async (response) => {
        if (cancelled) {
          return;
        }
        const fetchedChat = response.data;
        const preparedMessages = await prepareChatMessages(
          fetchedChat.messages,
          darkMode,
        );
        if (cancelled) {
          return;
        }
        startTransition(() => {
          setChat({ ...fetchedChat, messages: preparedMessages });
          setLoading(false);
        });
      })
      .catch((err) => {
        if (cancelled) {
          return;
        }
        if (err.response && err.response.status === 404) {
          setNotFound(true);
        } else {
          setError(err.message);
        }
        setLoading(false);
      });

    return () => {
      cancelled = true;
    };
    // Fetch once on mount. `darkMode` is read for the initial dual-theme
    // mermaid prewarm only; a later toggle is served from
    // `mermaidRenderCache` by each block's own render effect, so we must
    // not re-fetch (which would flash the spinner) on theme change --
    // mirroring ChatDetail's `[sessionId]`-only dependency.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

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

  if (notFound || !chat) {
    return (
      <Container sx={{ mt: 4 }}>
        <Typography variant="h5" gutterBottom>
          No chat to display
        </Typography>
        <Typography variant="body1" color="text.secondary" sx={{ mb: 3 }}>
          Open an exported chat JSON file to view it here, or go back to
          browse your indexed chats.
        </Typography>
        <Button
          component={Link}
          to="/"
          startIcon={<ArrowBackIcon />}
          variant="contained"
          color="highlight"
          sx={{ borderRadius: 2, color: 'white' }}
        >
          Back to all chats
        </Button>
      </Container>
    );
  }

  return (
    <Container sx={{ mb: 6 }}>
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

      <MessageList sessionId={chat.session_id || 'opened'} messages={messages} />
    </Container>
  );
};

export default ChatViewer;
