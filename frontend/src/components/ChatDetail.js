import React, { startTransition, useContext, useEffect, useMemo, useState } from 'react';
import { useParams, Link } from 'react-router-dom';
import axios from 'axios';
import {
  alpha,
  Avatar,
  Box,
  Button,
  Checkbox,
  Chip,
  CircularProgress,
  Container,
  Dialog,
  DialogActions,
  DialogContent,
  DialogContentText,
  DialogTitle,
  FormControl,
  FormControlLabel,
  Paper,
  Radio,
  RadioGroup,
  Typography,
} from '@mui/material';
import AccountTreeIcon from '@mui/icons-material/AccountTree';
import ArrowBackIcon from '@mui/icons-material/ArrowBack';
import CalendarTodayIcon from '@mui/icons-material/CalendarToday';
import DataObjectIcon from '@mui/icons-material/DataObject';
import FileDownloadIcon from '@mui/icons-material/FileDownload';
import FolderIcon from '@mui/icons-material/Folder';
import PersonIcon from '@mui/icons-material/Person';
import SmartToyIcon from '@mui/icons-material/SmartToy';
import StorageIcon from '@mui/icons-material/Storage';
import WarningIcon from '@mui/icons-material/Warning';
import MessageMarkdown from './MessageMarkdown';
import { prepareMarkdownHtml } from '../markdown/prepareMarkdownHtml';
import { ColorContext } from '../contexts/ColorContext';
import { ThemeModeContext } from '../contexts/ThemeModeContext';
import { exportChat } from '../utils/exportChat';

function formatDate(date) {
  try {
    if (!date) {
      return 'Unknown date';
    }
    const dateObject = new Date(date * 1000);
    if (Number.isNaN(dateObject.getTime())) {
      return 'Unknown date';
    }
    return dateObject.toLocaleString();
  } catch {
    return 'Unknown date';
  }
}

function getDbPathLabel(dbPath) {
  if (typeof dbPath !== 'string' || !dbPath) {
    return 'Unknown database';
  }
  return dbPath.split(/[\\/]/).pop();
}

const ChatDetail = () => {
  const colors = useContext(ColorContext);
  const { darkMode } = useContext(ThemeModeContext);
  const { sessionId } = useParams();
  const [chat, setChat] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [exportModalOpen, setExportModalOpen] = useState(false);
  const [formatDialogOpen, setFormatDialogOpen] = useState(false);
  const [exportFormat, setExportFormat] = useState('html');
  const [dontShowExportWarning, setDontShowExportWarning] = useState(false);

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
            if (typeof message.content !== 'string') {
              return message;
            }
            return {
              ...message,
              renderedContent: await prepareMarkdownHtml(message.content),
            };
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

    const warningPreference = document.cookie
      .split('; ')
      .find((row) => row.startsWith('dontShowExportWarning='));

    if (warningPreference) {
      setDontShowExportWarning(warningPreference.split('=')[1] === 'true');
    }

    return () => {
      cancelled = true;
    };
  }, [sessionId]);

  const handleFormatDialogOpen = () => {
    setFormatDialogOpen(true);
  };

  const handleFormatDialogClose = (confirmed) => {
    setFormatDialogOpen(false);

    if (!confirmed) {
      return;
    }

    if (dontShowExportWarning) {
      proceedWithExport(exportFormat);
    } else {
      setExportModalOpen(true);
    }
  };

  const handleExportWarningClose = (confirmed) => {
    setExportModalOpen(false);

    // TODO(bug): The cookie is written regardless of `confirmed`, so a
    // user who ticks the "Don't show this warning again" checkbox and
    // then closes the dialog with Cancel still has the preference
    // persisted. The guard should be `if (confirmed && dontShowExportWarning)`
    // to only remember the preference after an affirmative export.
    if (dontShowExportWarning) {
      const expiryDate = new Date();
      expiryDate.setFullYear(expiryDate.getFullYear() + 1);
      document.cookie = `dontShowExportWarning=true; expires=${expiryDate.toUTCString()}; path=/`;
    }

    if (confirmed) {
      proceedWithExport(exportFormat);
    }
  };

  const handleExport = () => {
    handleFormatDialogOpen();
  };

  const proceedWithExport = async (format) => {
    const result = await exportChat({ sessionId, format, darkMode });
    if (result.saved) {
      if (result.path) {
        alert(`Saved to ${result.path}`);
      }
      return;
    }
    if (result.cancelled) {
      return;
    }
    alert(`Failed to export chat: ${result.error || 'Unknown error'}`);
  };

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

  const dateDisplay = formatDate(chat.date);
  const projectName = chat.project?.name || 'Unknown Project';

  return (
    <Container sx={{ mb: 6 }}>
      <Dialog
        open={formatDialogOpen}
        onClose={() => handleFormatDialogClose(false)}
        aria-labelledby="format-selection-dialog-title"
      >
        <DialogTitle id="format-selection-dialog-title" sx={{ display: 'flex', alignItems: 'center' }}>
          <FileDownloadIcon sx={{ color: colors.highlightColor, mr: 1 }} />
          Export Format
        </DialogTitle>
        <DialogContent>
          <DialogContentText>
            Please select the export format for your chat:
          </DialogContentText>
          <FormControl component="fieldset" sx={{ mt: 2 }}>
            <RadioGroup
              aria-label="export-format"
              name="export-format"
              value={exportFormat}
              onChange={(event) => setExportFormat(event.target.value)}
            >
              <FormControlLabel value="html" control={<Radio />} label="HTML" />
              <FormControlLabel value="json" control={<Radio />} label="JSON" />
              <FormControlLabel value="markdown" control={<Radio />} label="Markdown" />
            </RadioGroup>
          </FormControl>
        </DialogContent>
        <DialogActions>
          <Button onClick={() => handleFormatDialogClose(false)} color="highlight">
            Cancel
          </Button>
          <Button onClick={() => handleFormatDialogClose(true)} color="highlight" variant="contained">
            Continue
          </Button>
        </DialogActions>
      </Dialog>

      <Dialog
        open={exportModalOpen}
        onClose={() => handleExportWarningClose(false)}
        aria-labelledby="export-warning-dialog-title"
      >
        <DialogTitle id="export-warning-dialog-title" sx={{ display: 'flex', alignItems: 'center' }}>
          <WarningIcon sx={{ color: 'warning.main', mr: 1 }} />
          Export Warning
        </DialogTitle>
        <DialogContent>
          <DialogContentText>
            Please make sure your exported chat doesn&apos;t include sensitive data such as API keys and customer information.
          </DialogContentText>
          <FormControlLabel
            control={(
              <Checkbox
                checked={dontShowExportWarning}
                onChange={(event) => setDontShowExportWarning(event.target.checked)}
              />
            )}
            label="Don't show this warning again"
            sx={{ mt: 2 }}
          />
        </DialogContent>
        <DialogActions>
          <Button onClick={() => handleExportWarningClose(false)} color="highlight">
            Cancel
          </Button>
          <Button onClick={() => handleExportWarningClose(true)} color="highlight" variant="contained">
            Continue Export
          </Button>
        </DialogActions>
      </Dialog>

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
          onClick={handleExport}
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

      <Paper
        sx={{
          px: 3,
          py: 2,
          mb: 3,
          overflow: 'hidden',
          boxShadow: '0 4px 12px rgba(0,0,0,0.08)',
        }}
      >
        <Box sx={{ display: 'flex', alignItems: 'center', flexWrap: 'wrap', gap: 1, mb: 1.5 }}>
          <FolderIcon sx={{ mr: 0.5, fontSize: 24, color: colors.highlightColor }} />
          <Typography variant="h6" fontWeight="600" color="text.primary" sx={{ mr: 1 }}>
            {projectName}
          </Typography>
          <Chip
            icon={<CalendarTodayIcon />}
            label={dateDisplay}
            size="small"
            sx={{
              fontWeight: 500,
              color: 'white',
              backgroundColor: colors.highlightColor,
              '& .MuiChip-icon': { color: 'white' },
              '& .MuiChip-label': { px: 1 },
            }}
          />
        </Box>

        <Box
          sx={{
            display: 'flex',
            flexWrap: 'wrap',
            gap: 2,
            alignItems: 'center',
          }}
        >
          <Box sx={{ display: 'flex', alignItems: 'center' }}>
            <AccountTreeIcon sx={{ mr: 0.5, color: colors.highlightColor, opacity: 0.8, fontSize: 18 }} />
            <Typography variant="body2" color="text.secondary">
              <strong>Path:</strong> {chat.project?.rootPath || 'Unknown location'}
            </Typography>
          </Box>

          {chat.workspace_id && (
            <Box sx={{ display: 'flex', alignItems: 'center' }}>
              <StorageIcon sx={{ mr: 0.5, color: colors.highlightColor, opacity: 0.8, fontSize: 18 }} />
              <Typography variant="body2" color="text.secondary">
                <strong>Workspace:</strong> {chat.workspace_id}
              </Typography>
            </Box>
          )}

          {chat.db_path && (
            <Box sx={{ display: 'flex', alignItems: 'center' }}>
              <DataObjectIcon sx={{ mr: 0.5, color: colors.highlightColor, opacity: 0.8, fontSize: 18 }} />
              <Typography variant="body2" color="text.secondary" sx={{ wordBreak: 'break-all' }}>
                <strong>DB:</strong> {getDbPathLabel(chat.db_path)}
              </Typography>
            </Box>
          )}
        </Box>
      </Paper>

      <Typography variant="h5" gutterBottom fontWeight="600" sx={{ mt: 4, mb: 3 }}>
        Conversation History
      </Typography>

      {messages.length === 0 ? (
        <Paper sx={{ p: 4, textAlign: 'center', borderRadius: 3 }}>
          <Typography variant="body1">
            No messages found in this conversation.
          </Typography>
        </Paper>
      ) : (
        <Box sx={{ mb: 4 }}>
          {messages.map((message, index) => (
            <Box key={index} sx={{ mb: 3.5 }}>
              <Box sx={{ display: 'flex', alignItems: 'center', mb: 1.5 }}>
                <Avatar
                  sx={{
                    bgcolor: message.role === 'user' ? colors.highlightColor : colors.secondary.main,
                    width: 32,
                    height: 32,
                    mr: 1.5,
                    boxShadow: '0 2px 4px rgba(0,0,0,0.1)',
                  }}
                >
                  {message.role === 'user' ? <PersonIcon /> : <SmartToyIcon />}
                </Avatar>
                <Typography variant="subtitle1" fontWeight="600">
                  {message.role === 'user' ? 'User' : 'Cursor'}
                </Typography>
              </Box>

              <Paper
                elevation={1}
                sx={{
                  p: 2.5,
                  ml: message.role === 'user' ? 0 : 5,
                  mr: message.role === 'assistant' ? 0 : 5,
                  backgroundColor: alpha(colors.highlightColor, 0.04),
                  borderLeft: '4px solid',
                  borderColor: message.role === 'user' ? colors.highlightColor : colors.secondary.main,
                  borderRadius: 2,
                }}
              >
                <Box
                  sx={{
                    '& img': { maxWidth: '100%' },
                    '& ul, & ol': { pl: 3 },
                    '& a': {
                      color: message.role === 'user' ? colors.highlightColor : colors.secondary.main,
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
                    '& th': {
                      fontWeight: 600,
                      backgroundColor: alpha(colors.highlightColor, 0.08),
                    },
                    '& tr:nth-of-type(even)': {
                      backgroundColor: alpha(colors.highlightColor, 0.03),
                    },
                  }}
                >
                  {typeof message.renderedContent === 'string' ? (
                    <MessageMarkdown
                      html={message.renderedContent}
                      colors={colors}
                      role={message.role}
                    />
                  ) : (
                    <Typography>Content unavailable</Typography>
                  )}
                </Box>
              </Paper>
            </Box>
          ))}
        </Box>
      )}
    </Container>
  );
};

export default ChatDetail;
