import React from 'react';
import { Box, Paper, Typography } from '@mui/material';
import MessageBubble from './MessageBubble';

// Renders either an empty-state Paper when the chat has no messages or
// a stack of MessageBubble siblings. Kept out of ChatDetail.js so the
// page composition stays readable. ``sessionId`` is threaded through so
// each bubble's image gallery can build ``/api/chat/:id/image/:uuid``
// URLs without reading the URL params again.
export default function MessageList({ sessionId, messages }) {
  if (messages.length === 0) {
    return (
      <Paper sx={{ p: 4, textAlign: 'center', borderRadius: 3 }}>
        <Typography variant="body1">
          No messages found in this conversation.
        </Typography>
      </Paper>
    );
  }

  return (
    <Box sx={{ mb: 4 }}>
      {messages.map((message, index) => (
        <MessageBubble key={index} sessionId={sessionId} message={message} />
      ))}
    </Box>
  );
}
