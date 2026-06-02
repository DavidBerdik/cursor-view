import React, {
  useCallback,
  useContext,
  useMemo,
  useState,
} from 'react';
import {
  Box,
  Button,
  CircularProgress,
  Container,
  Typography,
} from '@mui/material';
import RefreshIcon from '@mui/icons-material/Refresh';
import { ThemeModeContext } from '../../contexts/ThemeModeContext';
import { useChatSummaries } from '../../hooks/useChatSummaries';
import { useDebouncedValue } from '../../hooks/useDebouncedValue';
import { useExportFlow } from '../../hooks/useExportFlow';
import ExportFormatDialog from '../export/ExportFormatDialog';
import ExportWarningDialog from '../export/ExportWarningDialog';
import ExportRevealSnackbar from '../export/ExportRevealSnackbar';
import EmptyState from './EmptyState';
import ProjectGroup from './ProjectGroup';
import SearchBar from './SearchBar';

const SEARCH_DEBOUNCE_MS = 200;

const ChatList = () => {
  const { darkMode } = useContext(ThemeModeContext);
  const [expandedProjects, setExpandedProjects] = useState({});
  const [searchQuery, setSearchQuery] = useState('');
  // Debouncing the *dependency* of useChatSummaries' fetch effect is
  // what keeps a fast typist from firing one /api/chats request per
  // keystroke; useDeferredValue would only re-prioritize the render,
  // not the network call.
  const debouncedSearchQuery = useDebouncedValue(searchQuery.trim(), SEARCH_DEBOUNCE_MS);
  const { chatData, loading, error, refresh } = useChatSummaries(debouncedSearchQuery);
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
    snackbarOpen,
    closeSnackbar,
    revealSavedFile,
  } = useExportFlow({ darkMode });

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

  // Stable callbacks keep React.memo on ProjectGroup / ChatCard
  // effective: a fresh closure per render would invalidate the memo
  // and re-reconcile every row on every keystroke.
  const handleProjectToggle = useCallback((projectKey) => {
    setExpandedProjects((previous) => ({
      ...previous,
      [projectKey]: !previous[projectKey],
    }));
  }, []);

  const clearSearch = useCallback(() => {
    setSearchQuery('');
  }, []);

  const handleSearchChange = useCallback((event) => {
    setSearchQuery(event.target.value);
  }, []);

  // Intercepts the click inside the <Link>-wrapped Card so hitting
  // the export button doesn't also navigate to the chat detail route.
  const handleCardExport = useCallback((event, sessionId) => {
    event.preventDefault();
    event.stopPropagation();
    requestExport(sessionId);
  }, [requestExport]);

  if (loading && chatData.items.length === 0) {
    return (
      <Container sx={{ display: 'flex', justifyContent: 'center', alignItems: 'center', height: '70vh' }}>
        <CircularProgress sx={{ color: 'var(--mui-palette-highlight-main)' }} />
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
          <Typography variant="h4" component="h1" sx={{ color: 'var(--mui-palette-text-primary)' }}>
            Cursor Chat History
          </Typography>
          <Typography variant="body2" color="text.secondary" sx={{ mt: 0.75 }}>
            {debouncedSearchQuery
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
              backgroundColor: 'rgba(var(--mui-palette-highlight-mainChannel) / 0.8)',
            },
          }}
        >
          Refresh
        </Button>
      </Box>

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

      <ExportRevealSnackbar
        open={snackbarOpen}
        onReveal={revealSavedFile}
        onClose={closeSnackbar}
      />

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
          searchQuery={debouncedSearchQuery}
          onClearSearch={clearSearch}
          onRetry={refresh}
        />
      ) : (
        groupedProjects.map((project) => (
          <ProjectGroup
            key={project.key}
            project={project}
            isExpanded={!!expandedProjects[project.key]}
            onToggle={handleProjectToggle}
            onExport={handleCardExport}
            dontShowExportWarning={dontShow}
          />
        ))
      )}
    </Container>
  );
};

export default ChatList;
