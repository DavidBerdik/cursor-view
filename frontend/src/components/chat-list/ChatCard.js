import React, { useContext } from 'react';
import { Link } from 'react-router-dom';
import {
  alpha,
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
import { ColorContext } from '../../contexts/ColorContext';
import { dbPathLabel } from '../../utils/dbPath';
import { formatDate } from '../../utils/formatDate';

// Single-chat card in the project group grid. The whole card is a
// <Link> to the detail route so the entire surface is clickable; the
// export button stops propagation so clicking it doesn't also navigate.
export default function ChatCard({ chat, dontShowExportWarning, onExport }) {
  const colors = useContext(ColorContext);
  const dateDisplay = formatDate(chat.date);

  return (
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
            DB: {dbPathLabel(chat.db_path, { segments: 2 })}
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
