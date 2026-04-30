import React, { memo } from 'react';
import { Link } from 'react-router-dom';
import {
  Box,
  Card,
  CardActions,
  CardContent,
  Divider,
  IconButton,
  Tooltip,
  Typography,
} from '@mui/material';
import CalendarTodayIcon from '@mui/icons-material/CalendarToday';
import FileDownloadIcon from '@mui/icons-material/FileDownload';
import MessageIcon from '@mui/icons-material/Message';
import {
  PALETTE_TRANSITION,
  PALETTE_TRANSITION_CURVE,
  PALETTE_TRANSITION_DURATION,
} from '../../theme/transitions';
import { dbPathLabel } from '../../utils/dbPath';
import { formatDate } from '../../utils/formatDate';

// Single-chat card in the project group grid. The whole card is a
// <Link> to the detail route so the entire surface is clickable; the
// export button stops propagation so clicking it doesn't also navigate.
//
// Wrapped in ``React.memo`` because hundreds of these cards render
// inside a single ProjectGroup grid; each chatData swap from the
// debounced search would otherwise reconcile every card even when
// its row data hadn't changed. The parent supplies ``onExport`` and
// ``dontShowExportWarning`` as ``useCallback``-stable / primitive
// values so reference equality holds across renders.
function ChatCard({ chat, dontShowExportWarning, onExport }) {
  const dateDisplay = formatDate(chat.date);

  return (
    <Card
      component={Link}
      to={`/chat/${chat.session_id}`}
      sx={{
        height: '100%',
        display: 'flex',
        flexDirection: 'column',
        textDecoration: 'none',
        borderTop: '1px solid',
        borderColor: 'rgba(var(--mui-palette-text-secondaryChannel) / 0.1)',
        // The centralized `MuiCard` styleOverride sets `transition:
        // PALETTE_TRANSITION`, which intentionally omits `transform`
        // so hundreds of unrelated `MuiCard` consumers don't carry
        // a per-element `transform`-transition entry just to support
        // this one card's hover-lift. We compose the centralized
        // string with an extra `transform` entry locally here, which
        // is the only site in the codebase that needs `transform`
        // animation. See `theme/transitions.js` for the rationale.
        transition: `${PALETTE_TRANSITION}, transform ${PALETTE_TRANSITION_DURATION} ${PALETTE_TRANSITION_CURVE}`,
        '&:hover': {
          transform: 'translateY(-8px)',
          boxShadow: '0 20px 25px -5px rgba(0,0,0,0.1), 0 10px 10px -5px rgba(0,0,0,0.04)',
        },
      }}
    >
      <CardContent>
        {chat.title && (
          <Typography
            variant="subtitle2"
            fontWeight={700}
            noWrap
            sx={{ mb: 1, color: 'text.primary' }}
          >
            {chat.title}
          </Typography>
        )}
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
          <MessageIcon fontSize="small" sx={{ mr: 1, color: 'var(--mui-palette-text-secondary)' }} />
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
            DB: {dbPathLabel(chat.db_path, { segments: 2 })}
          </Typography>
        )}

        <Box
          sx={{
            mt: 2,
            p: 1.5,
            backgroundColor: 'rgba(var(--mui-palette-highlight-mainChannel) / 0.1)',
            borderRadius: 2,
            border: '1px solid',
            borderColor: 'rgba(var(--mui-palette-text-secondaryChannel) / 0.05)',
            transition: PALETTE_TRANSITION,
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
            onClick={(event) => onExport(event, chat.session_id)}
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
  );
}

export default memo(ChatCard);
