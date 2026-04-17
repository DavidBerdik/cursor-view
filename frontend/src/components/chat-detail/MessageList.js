import React from 'react';
import { Box, Paper, Typography } from '@mui/material';
import MessageBubble from './MessageBubble';

// Renders either an empty-state Paper when the chat has no messages or
// a stack of MessageBubble siblings. Kept out of ChatDetail.js so the
// page composition stays readable.
export default function MessageList({ messages }) {
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
        <MessageBubble key={index} message={message} />
      ))}
    </Box>
  );
}
