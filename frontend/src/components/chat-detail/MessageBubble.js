import React, { useContext } from 'react';
import { alpha, Avatar, Box, Paper, Typography } from '@mui/material';
import PersonIcon from '@mui/icons-material/Person';
import SmartToyIcon from '@mui/icons-material/SmartToy';
import MessageMarkdown from '../MessageMarkdown';
import { ColorContext } from '../../contexts/ColorContext';

// One user/assistant bubble: avatar + role label in the header row,
// then a Paper with the pre-rendered markdown HTML (done upstream in
// ChatDetail's effect via `prepareMarkdownHtml`). The Box around
// MessageMarkdown owns the in-chat styling for links, tables, lists,
// and images so the markdown output blends with the chat theme.
export default function MessageBubble({ message }) {
  const colors = useContext(ColorContext);
  const isUser = message.role === 'user';
  const accent = isUser ? colors.highlightColor : colors.secondary.main;

  return (
    <Box sx={{ mb: 3.5 }}>
      <Box sx={{ display: 'flex', alignItems: 'center', mb: 1.5 }}>
        <Avatar
          sx={{
            bgcolor: accent,
            width: 32,
            height: 32,
            mr: 1.5,
            boxShadow: '0 2px 4px rgba(0,0,0,0.1)',
          }}
        >
          {isUser ? <PersonIcon /> : <SmartToyIcon />}
        </Avatar>
        <Typography variant="subtitle1" fontWeight="600">
          {isUser ? 'User' : 'Cursor'}
        </Typography>
      </Box>

      <Paper
        elevation={1}
        sx={{
          p: 2.5,
          ml: isUser ? 0 : 5,
          mr: isUser ? 5 : 0,
          backgroundColor: alpha(colors.highlightColor, 0.04),
          borderLeft: '4px solid',
          borderColor: accent,
          borderRadius: 2,
        }}
      >
        <Box
          sx={{
            '& img': { maxWidth: '100%' },
            '& ul, & ol': { pl: 3 },
            '& a': {
              color: accent,
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
  );
}
