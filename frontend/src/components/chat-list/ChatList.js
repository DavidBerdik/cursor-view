import React, {
  useContext,
  useDeferredValue,
  useEffect,
  useMemo,
  useState,
} from 'react';
import {
  alpha,
  Box,
  Button,
  Checkbox,
  CircularProgress,
  Container,
  Dialog,
  DialogActions,
  DialogContent,
  DialogContentText,
  DialogTitle,
  FormControl,
  FormControlLabel,
  Radio,
  RadioGroup,
  Typography,
} from '@mui/material';
import FileDownloadIcon from '@mui/icons-material/FileDownload';
import RefreshIcon from '@mui/icons-material/Refresh';
import WarningIcon from '@mui/icons-material/Warning';
import { ColorContext } from '../../contexts/ColorContext';
import { ThemeModeContext } from '../../contexts/ThemeModeContext';
import { useChatSummaries } from '../../hooks/useChatSummaries';
import { exportChat } from '../../utils/exportChat';
import EmptyState from './EmptyState';
import ProjectGroup from './ProjectGroup';
import SearchBar from './SearchBar';

const ChatList = () => {
  const colors = useContext(ColorContext);
  const { darkMode } = useContext(ThemeModeContext);
  const [expandedProjects, setExpandedProjects] = useState({});
  const [searchQuery, setSearchQuery] = useState('');
  const [exportModalOpen, setExportModalOpen] = useState(false);
  const [formatDialogOpen, setFormatDialogOpen] = useState(false);
  const [exportFormat, setExportFormat] = useState('html');
  const [dontShowExportWarning, setDontShowExportWarning] = useState(false);
  const [currentExportSession, setCurrentExportSession] = useState(null);
  const deferredSearchQuery = useDeferredValue(searchQuery.trim());
  const { chatData, loading, error, refresh } = useChatSummaries(deferredSearchQuery);

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
          onClick={refresh}
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

      <SearchBar
        value={searchQuery}
        onChange={handleSearchChange}
        onClear={clearSearch}
      />

      {error && (
        <Typography variant="body2" color="error" sx={{ mb: 2 }}>
          Error refreshing chats: {error}
        </Typography>
      )}

      {groupedProjects.length === 0 ? (
        <EmptyState
          searchQuery={deferredSearchQuery}
          onClearSearch={clearSearch}
          onRetry={refresh}
        />
      ) : (
        groupedProjects.map((project) => (
          <ProjectGroup
            key={project.key}
            project={project}
            isExpanded={!!expandedProjects[project.key]}
            onToggle={() => toggleProjectExpand(project.key)}
            onExport={handleExport}
            dontShowExportWarning={dontShowExportWarning}
          />
        ))
      )}
    </Container>
  );
};

export default ChatList;
