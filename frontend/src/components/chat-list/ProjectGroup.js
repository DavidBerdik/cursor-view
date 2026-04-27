import React, { memo, useCallback, useContext } from 'react';
import {
  alpha,
  Box,
  Chip,
  Collapse,
  Grid,
  IconButton,
  Paper,
  Typography,
} from '@mui/material';
import ExpandLessIcon from '@mui/icons-material/ExpandLess';
import ExpandMoreIcon from '@mui/icons-material/ExpandMore';
import FolderIcon from '@mui/icons-material/Folder';
import { ColorContext } from '../../contexts/ColorContext';
import ChatCard from './ChatCard';

// One collapsible card per distinct project: the header (folder icon,
// project name, chat count chip, expand button, path subtitle) plus the
// Collapse region that reveals a responsive grid of ChatCard siblings.
//
// ``onToggle`` is ``(projectKey) => void`` (not a zero-arg closure),
// so the parent can pass a single ``useCallback``-stable handler
// shared by every group. The matching ``React.memo`` wrap below then
// actually holds: an unchanged group's props no longer get
// invalidated by a fresh per-render closure on every keystroke.
function ProjectGroup({
  project,
  isExpanded,
  onToggle,
  onExport,
  dontShowExportWarning,
}) {
  const colors = useContext(ColorContext);
  const chatCountLabel = `${project.chats.length} ${project.chats.length === 1 ? 'chat' : 'chats'}`;

  const handleToggle = useCallback(() => {
    onToggle(project.key);
  }, [onToggle, project.key]);

  const handleIconClick = useCallback((event) => {
    event.stopPropagation();
    onToggle(project.key);
  }, [onToggle, project.key]);

  return (
    <Box sx={{ mb: 4 }}>
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
          onClick={handleToggle}
        >
          <Box sx={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
            <Box sx={{ display: 'flex', alignItems: 'center' }}>
              <FolderIcon sx={{ mr: 1.5, fontSize: 28, color: colors.text.secondary }} />
              <Typography variant="h6" sx={{ fontWeight: 600 }}>
                {project.name}
              </Typography>
              <Chip
                label={chatCountLabel}
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
              onClick={handleIconClick}
            >
              {isExpanded ? <ExpandLessIcon /> : <ExpandMoreIcon />}
            </IconButton>
          </Box>
          <Typography variant="body2" sx={{ color: colors.text.secondary, mt: 0.5 }}>
            {project.path}
          </Typography>
        </Box>
      </Paper>

      {/*
        ``mountOnEnter unmountOnExit`` keeps collapsed groups out of
        the DOM. With hundreds of chats spread across many projects
        most groups are collapsed at any given moment; without these
        flags every ChatCard would still be reconciled (and laid out
        with display:none) on every list-data swap.
      */}
      <Collapse in={isExpanded} mountOnEnter unmountOnExit>
        <Grid container spacing={3}>
          {project.chats.map((chat, index) => (
            <Grid size={{ xs: 12, sm: 6, md: 4 }} key={chat.session_id || `chat-${index}`}>
              <ChatCard
                chat={chat}
                dontShowExportWarning={dontShowExportWarning}
                onExport={onExport}
              />
            </Grid>
          ))}
        </Grid>
      </Collapse>
    </Box>
  );
}

export default memo(ProjectGroup);
