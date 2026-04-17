import React, {
  startTransition,
  useContext,
  useDeferredValue,
  useEffect,
  useMemo,
  useState,
} from 'react';
import { Link } from 'react-router-dom';
import axios from 'axios';
import {
  alpha,
  Box,
  Button,
  Card,
  CardActions,
  CardContent,
  Checkbox,
  Chip,
  CircularProgress,
  Collapse,
  Container,
  Dialog,
  DialogActions,
  DialogContent,
  DialogContentText,
  DialogTitle,
  Divider,
  FormControl,
  FormControlLabel,
  Grid,
  IconButton,
  InputAdornment,
  Paper,
  Radio,
  RadioGroup,
  TextField,
  Tooltip,
  Typography,
} from '@mui/material';
import CalendarTodayIcon from '@mui/icons-material/CalendarToday';
import ClearIcon from '@mui/icons-material/Clear';
import ExpandLessIcon from '@mui/icons-material/ExpandLess';
import ExpandMoreIcon from '@mui/icons-material/ExpandMore';
import FileDownloadIcon from '@mui/icons-material/FileDownload';
import FolderIcon from '@mui/icons-material/Folder';
import InfoIcon from '@mui/icons-material/Info';
import MessageIcon from '@mui/icons-material/Message';
import RefreshIcon from '@mui/icons-material/Refresh';
import SearchIcon from '@mui/icons-material/Search';
import WarningIcon from '@mui/icons-material/Warning';
import { ColorContext, ThemeModeContext } from '../App';

function getDbPathLabel(dbPath) {
  if (typeof dbPath !== 'string' || !dbPath) {
    return 'Unknown database';
  }
  return dbPath.split(/[\\/]/).slice(-2).join('/');
}

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

async function fetchChatSummaries(query, refresh = false) {
  const params = new URLSearchParams();
  if (query) {
    params.set('q', query);
  }
  if (refresh) {
    params.set('refresh', '1');
  }
  const suffix = params.toString() ? `?${params.toString()}` : '';
  const response = await axios.get(`/api/chats${suffix}`);
  return response.data;
}

const ChatList = () => {
  const colors = useContext(ColorContext);
  const { darkMode } = useContext(ThemeModeContext);
  const [chatData, setChatData] = useState({ items: [], total: 0 });
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [expandedProjects, setExpandedProjects] = useState({});
  const [searchQuery, setSearchQuery] = useState('');
  const [exportModalOpen, setExportModalOpen] = useState(false);
  const [formatDialogOpen, setFormatDialogOpen] = useState(false);
  const [exportFormat, setExportFormat] = useState('html');
  const [dontShowExportWarning, setDontShowExportWarning] = useState(false);
  const [currentExportSession, setCurrentExportSession] = useState(null);
  const deferredSearchQuery = useDeferredValue(searchQuery.trim());

  useEffect(() => {
    let cancelled = false;

    setLoading(true);
    setError(null);

    fetchChatSummaries(deferredSearchQuery)
      .then((payload) => {
        if (cancelled) {
          return;
        }
        // Keep setLoading(false) inside the same transition as setChatData so React
        // never commits loading=false while items are still empty (avoids empty-state flash).
        startTransition(() => {
          setChatData({
            items: Array.isArray(payload.items) ? payload.items : [],
            total: Number.isFinite(payload.total) ? payload.total : 0,
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
  }, [deferredSearchQuery]);

  useEffect(() => {
    const warningPreference = document.cookie
      .split('; ')
      .find((row) => row.startsWith('dontShowExportWarning='));

    if (warningPreference) {
      setDontShowExportWarning(warningPreference.split('=')[1] === 'true');
    }
  }, []);

  const groupedProjects = useMemo(() => {
    const projectMap = new Map();

    chatData.items.forEach((chat) => {
      const projectName = chat.project?.name || 'Unknown Project';
      const projectPath = chat.project?.rootPath || 'Unknown';
      const projectKey = `${projectName}::${projectPath}`;
      const existing = projectMap.get(projectKey);

      if (existing) {
        existing.chats.push(chat);
        return;
      }

      projectMap.set(projectKey, {
        key: projectKey,
        name: projectName,
        path: projectPath,
        chats: [chat],
      });
    });

    return Array.from(projectMap.values());
  }, [chatData.items]);

  const toggleProjectExpand = (projectKey) => {
    setExpandedProjects((previous) => ({
      ...previous,
      [projectKey]: !previous[projectKey],
    }));
  };

  const clearSearch = () => {
    setSearchQuery('');
  };

  const handleSearchChange = (event) => {
    setSearchQuery(event.target.value);
  };

  const handleRefresh = async () => {
    setLoading(true);
    setError(null);
    try {
      const payload = await fetchChatSummaries(deferredSearchQuery, true);
      startTransition(() => {
        setChatData({
          items: Array.isArray(payload.items) ? payload.items : [],
          total: Number.isFinite(payload.total) ? payload.total : 0,
        });
        setLoading(false);
      });
    } catch (err) {
      setError(err.message);
      setLoading(false);
    }
  };

  const handleFormatDialogClose = (confirmed) => {
    setFormatDialogOpen(false);
    if (!confirmed) {
      setCurrentExportSession(null);
      return;
    }
    if (dontShowExportWarning && currentExportSession) {
      proceedWithExport(currentExportSession, exportFormat);
      setCurrentExportSession(null);
    } else if (currentExportSession) {
      setExportModalOpen(true);
    }
  };

  const handleExportWarningClose = (confirmed) => {
    setExportModalOpen(false);

    if (dontShowExportWarning) {
      const expiryDate = new Date();
      expiryDate.setFullYear(expiryDate.getFullYear() + 1);
      document.cookie = `dontShowExportWarning=true; expires=${expiryDate.toUTCString()}; path=/`;
    }

    if (confirmed && currentExportSession) {
      proceedWithExport(currentExportSession, exportFormat);
    }

    setCurrentExportSession(null);
  };

  const handleExport = (event, sessionId) => {
    event.preventDefault();
    event.stopPropagation();
    setCurrentExportSession(sessionId);
    setFormatDialogOpen(true);
  };

  const proceedWithExport = async (sessionId, format) => {
    try {
      const params = new URLSearchParams({
        format,
        theme: darkMode ? 'dark' : 'light',
      });
      const response = await axios.get(
        `/api/chat/${sessionId}/export?${params.toString()}`,
        { responseType: 'blob' },
      );

      const blob = response.data;

      if (!blob || blob.size === 0) {
        throw new Error('Received empty or invalid content from server');
      }

      const mimeType =
        format === 'json'
          ? 'application/json;charset=utf-8'
          : format === 'markdown'
            ? 'text/markdown;charset=utf-8'
            : 'text/html;charset=utf-8';
      const typedBlob = blob.type ? blob : new Blob([blob], { type: mimeType });
      const extension =
        format === 'json' ? 'json' : format === 'markdown' ? 'md' : 'html';
      const filename = `cursor-chat-${sessionId.slice(0, 8)}.${extension}`;
      const link = document.createElement('a');
      const url = URL.createObjectURL(typedBlob);

      link.href = url;
      link.download = filename;
      document.body.appendChild(link);
      link.click();
      document.body.removeChild(link);
      URL.revokeObjectURL(url);
    } catch (exportError) {
      const errorMessage = exportError.response
        ? `Server error: ${exportError.response.status}`
        : exportError.request
          ? 'No response received from server'
          : exportError.message || 'Unknown error setting up request';
      alert(`Failed to export chat: ${errorMessage}`);
    }
  };

  if (loading && chatData.items.length === 0) {
    return (
      <Container sx={{ display: 'flex', justifyContent: 'center', alignItems: 'center', height: '70vh' }}>
        <CircularProgress sx={{ color: colors.highlightColor }} />
      </Container>
    );
  }

  if (error && chatData.items.length === 0) {
    return (
      <Container>
        <Typography variant="h5" color="error">
          Error: {error}
        </Typography>
      </Container>
    );
  }

  return (
    <Container maxWidth="lg" sx={{ mt: 4, mb: 4 }}>
      <Box sx={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', gap: 2, mb: 3 }}>
        <Box>
          <Typography variant="h4" component="h1" sx={{ color: colors.text.primary }}>
            Cursor Chat History
          </Typography>
          <Typography variant="body2" color="text.secondary" sx={{ mt: 0.75 }}>
            {deferredSearchQuery
              ? `${chatData.total} matching chats`
              : `${chatData.total} chats indexed`}
          </Typography>
        </Box>
        <Button
          variant="contained"
          color="highlight"
          startIcon={loading ? <CircularProgress size={16} color="inherit" /> : <RefreshIcon />}
          onClick={handleRefresh}
          disabled={loading}
          sx={{
            borderRadius: 2,
            color: 'white',
            '&:hover': {
              backgroundColor: alpha(colors.highlightColor, 0.8),
            },
          }}
        >
          Refresh
        </Button>
      </Box>

      <Dialog
        open={formatDialogOpen}
        onClose={() => handleFormatDialogClose(false)}
        aria-labelledby="chatlist-format-selection-dialog-title"
      >
        <DialogTitle id="chatlist-format-selection-dialog-title" sx={{ display: 'flex', alignItems: 'center' }}>
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
          <Button onClick={() => handleExportWarningClose(false)} color="primary">
            Cancel
          </Button>
          <Button onClick={() => handleExportWarningClose(true)} color="highlight" variant="contained">
            Continue Export
          </Button>
        </DialogActions>
      </Dialog>

      <TextField
        fullWidth
        variant="outlined"
        placeholder="Search by project name or chat content..."
        value={searchQuery}
        onChange={handleSearchChange}
        size="medium"
        sx={{ mb: 3 }}
        InputProps={{
          startAdornment: (
            <InputAdornment position="start">
              <SearchIcon color="action" />
            </InputAdornment>
          ),
          endAdornment: searchQuery && (
            <InputAdornment position="end">
              <IconButton
                size="small"
                aria-label="clear search"
                onClick={clearSearch}
                edge="end"
              >
                <ClearIcon />
              </IconButton>
            </InputAdornment>
          ),
          sx: { borderRadius: 2 },
        }}
      />

      {error && (
        <Typography variant="body2" color="error" sx={{ mb: 2 }}>
          Error refreshing chats: {error}
        </Typography>
      )}

      {groupedProjects.length === 0 ? (
        <Paper
          sx={{
            p: 4,
            textAlign: 'center',
            borderRadius: 4,
            boxShadow: '0 10px 15px -3px rgba(0, 0, 0, 0.1), 0 4px 6px -2px rgba(0, 0, 0, 0.05)',
          }}
        >
          <InfoIcon sx={{ fontSize: 60, color: 'primary.main', mb: 2 }} />
          <Typography variant="h5" gutterBottom fontWeight="600">
            {deferredSearchQuery ? 'No Results Found' : 'No Chat History Found'}
          </Typography>
          <Typography variant="body1" sx={{ mb: 2 }}>
            {deferredSearchQuery
              ? `We couldn't find any chats matching "${deferredSearchQuery}".`
              : "We couldn't find any Cursor chat data on your system. This could be because:"}
          </Typography>
          {!deferredSearchQuery && (
            <Box sx={{ textAlign: 'left', maxWidth: '600px', mx: 'auto' }}>
              <Typography component="ul" variant="body2" sx={{ mb: 2 }}>
                <li>You haven&apos;t used Cursor&apos;s AI Assistant yet</li>
                <li>Your Cursor databases are stored in a non-standard location</li>
                <li>There might be permission issues accessing the database files</li>
              </Typography>
            </Box>
          )}
          {deferredSearchQuery ? (
            <Button
              startIcon={<ClearIcon />}
              onClick={clearSearch}
              variant="contained"
              color="primary"
              size="large"
              sx={{ borderRadius: 2 }}
            >
              Clear Search
            </Button>
          ) : (
            <Button
              startIcon={<RefreshIcon />}
              onClick={handleRefresh}
              variant="contained"
              color="primary"
              size="large"
              sx={{ borderRadius: 2 }}
            >
              Retry Detection
            </Button>
          )}
        </Paper>
      ) : (
        groupedProjects.map((project) => {
          const isExpanded = !!expandedProjects[project.key];
          return (
            <Box key={project.key} sx={{ mb: 4 }}>
              <Paper
                sx={{
                  p: 0,
                  mb: 2,
                  overflow: 'hidden',
                  boxShadow: '0 4px 12px rgba(0,0,0,0.08)',
                  transition: 'all 0.3s ease-in-out',
                  '&:hover': {
                    boxShadow: '0 8px 24px rgba(0,0,0,0.12)',
                  },
                }}
              >
                <Box
                  sx={{
                    background: colors.background.paper,
                    borderBottom: '1px solid',
                    borderColor: alpha(colors.text.secondary, 0.1),
                    color: colors.text.primary,
                    p: 2,
                    cursor: 'pointer',
                    '&:hover': {
                      backgroundColor: alpha(colors.highlightColor, 0.02),
                    },
                  }}
                  onClick={() => toggleProjectExpand(project.key)}
                >
                  <Box sx={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
                    <Box sx={{ display: 'flex', alignItems: 'center' }}>
                      <FolderIcon sx={{ mr: 1.5, fontSize: 28, color: colors.text.secondary }} />
                      <Typography variant="h6" sx={{ fontWeight: 600 }}>
                        {project.name}
                      </Typography>
                      <Chip
                        label={`${project.chats.length} ${project.chats.length === 1 ? 'chat' : 'chats'}`}
                        size="small"
                        sx={{
                          ml: 2,
                          fontWeight: 500,
                          backgroundColor: colors.highlightColor,
                          color: 'white',
                          '& .MuiChip-label': {
                            px: 1.5,
                          },
                        }}
                      />
                    </Box>
                    <IconButton
                      aria-expanded={isExpanded}
                      aria-label="show more"
                      sx={{
                        color: 'white',
                        bgcolor: colors.highlightColor,
                        '&:hover': {
                          bgcolor: alpha(colors.highlightColor, 0.8),
                        },
                      }}
                      onClick={(event) => {
                        event.stopPropagation();
                        toggleProjectExpand(project.key);
                      }}
                    >
                      {isExpanded ? <ExpandLessIcon /> : <ExpandMoreIcon />}
                    </IconButton>
                  </Box>
                  <Typography variant="body2" sx={{ color: colors.text.secondary, mt: 0.5 }}>
                    {project.path}
                  </Typography>
                </Box>
              </Paper>

              <Collapse in={isExpanded}>
                <Grid container spacing={3}>
                  {project.chats.map((chat, index) => {
                    const dateDisplay = formatDate(chat.date);
                    return (
                      <Grid size={{ xs: 12, sm: 6, md: 4 }} key={chat.session_id || `chat-${index}`}>
                        <Card
                          component={Link}
                          to={`/chat/${chat.session_id}`}
                          sx={{
                            height: '100%',
                            display: 'flex',
                            flexDirection: 'column',
                            transition: 'all 0.3s cubic-bezier(.17,.67,.83,.67)',
                            textDecoration: 'none',
                            borderTop: '1px solid',
                            borderColor: alpha(colors.text.secondary, 0.1),
                            '&:hover': {
                              transform: 'translateY(-8px)',
                              boxShadow: '0 20px 25px -5px rgba(0,0,0,0.1), 0 10px 10px -5px rgba(0,0,0,0.04)',
                            },
                          }}
                        >
                          <CardContent>
                            <Box
                              sx={{
                                display: 'flex',
                                alignItems: 'center',
                                mb: 1.5,
                                justifyContent: 'space-between',
                              }}
                            >
                              <Box sx={{ display: 'flex', alignItems: 'center' }}>
                                <CalendarTodayIcon fontSize="small" sx={{ mr: 1, color: 'text.secondary' }} />
                                <Typography variant="body2" color="text.secondary">
                                  {dateDisplay}
                                </Typography>
                              </Box>
                            </Box>

                            <Divider sx={{ my: 1.5 }} />

                            <Box sx={{ display: 'flex', alignItems: 'center', mb: 1.5 }}>
                              <MessageIcon fontSize="small" sx={{ mr: 1, color: colors.text.secondary }} />
                              <Typography variant="body2" fontWeight="500">
                                {chat.message_count || 0} messages
                              </Typography>
                            </Box>

                            {chat.db_path && (
                              <Typography
                                variant="caption"
                                color="text.secondary"
                                sx={{
                                  display: 'block',
                                  mb: 1.5,
                                  overflow: 'hidden',
                                  textOverflow: 'ellipsis',
                                  whiteSpace: 'nowrap',
                                }}
                              >
                                DB: {getDbPathLabel(chat.db_path)}
                              </Typography>
                            )}

                            <Box
                              sx={{
                                mt: 2,
                                p: 1.5,
                                backgroundColor: alpha(colors.highlightColor, 0.1),
                                borderRadius: 2,
                                border: '1px solid',
                                borderColor: alpha(colors.text.secondary, 0.05),
                              }}
                            >
                              <Typography
                                variant="body2"
                                sx={{
                                  overflow: 'hidden',
                                  textOverflow: 'ellipsis',
                                  display: '-webkit-box',
                                  WebkitLineClamp: 2,
                                  WebkitBoxOrient: 'vertical',
                                  color: 'text.primary',
                                  fontWeight: 400,
                                }}
                              >
                                {chat.preview || 'Content unavailable'}
                              </Typography>
                            </Box>
                          </CardContent>
                          <CardActions sx={{ mt: 'auto', pt: 0 }}>
                            <Tooltip title="Export chat (Warning: Check for sensitive data)">
                              <IconButton
                                size="small"
                                onClick={(event) => handleExport(event, chat.session_id)}
                                sx={{
                                  ml: 'auto',
                                  position: 'relative',
                                  '&::after': dontShowExportWarning
                                    ? null
                                    : {
                                        content: '""',
                                        position: 'absolute',
                                        width: '6px',
                                        height: '6px',
                                        backgroundColor: 'warning.main',
                                        borderRadius: '50%',
                                        top: '2px',
                                        right: '2px',
                                      },
                                }}
                              >
                                <FileDownloadIcon fontSize="small" />
                              </IconButton>
                            </Tooltip>
                          </CardActions>
                        </Card>
                      </Grid>
                    );
                  })}
                </Grid>
              </Collapse>
            </Box>
          );
        })
      )}
    </Container>
  );
};

export default ChatList;
