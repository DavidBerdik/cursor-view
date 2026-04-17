import React, { useContext } from 'react';
import { Box, Chip, Paper, Typography } from '@mui/material';
import AccountTreeIcon from '@mui/icons-material/AccountTree';
import CalendarTodayIcon from '@mui/icons-material/CalendarToday';
import DataObjectIcon from '@mui/icons-material/DataObject';
import FolderIcon from '@mui/icons-material/Folder';
import StorageIcon from '@mui/icons-material/Storage';
import { ColorContext } from '../../contexts/ColorContext';

// Local helpers kept here for now; promoted to src/utils/ in a later
// refactor step so the chat-list side can share the same implementation.
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

// NOTE: ChatList uses ``slice(-2).join('/')`` on the same kind of DB
// path; this page shows only the trailing filename because it also
// surfaces the full ``Path:`` value next to it. Leave both shapes
// alone until utils/ extraction decides whether to unify them.
function getDbPathLabel(dbPath) {
  if (typeof dbPath !== 'string' || !dbPath) {
    return 'Unknown database';
  }
  return dbPath.split(/[\\/]/).pop();
}

// Compact project/date/path/workspace/db metadata strip rendered above
// the conversation. Consumes the active ColorContext for the highlight
// accent so dark/light modes pick up automatically.
export default function ChatMetaPanel({ chat }) {
  const colors = useContext(ColorContext);
  const dateDisplay = formatDate(chat.date);
  const projectName = chat.project?.name || 'Unknown Project';

  return (
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
  );
}
