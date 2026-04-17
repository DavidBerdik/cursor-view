import React from 'react';
import { Box, Button, Paper, Typography } from '@mui/material';
import ClearIcon from '@mui/icons-material/Clear';
import InfoIcon from '@mui/icons-material/Info';
import RefreshIcon from '@mui/icons-material/Refresh';

// Empty-state card shown when either (a) the user's search yielded no
// matches, or (b) no Cursor chat data was discovered on the system at
// all. The `searchQuery` prop switches between those two copy/CTA modes.
export default function EmptyState({ searchQuery, onClearSearch, onRetry }) {
  const isSearchEmpty = Boolean(searchQuery);
  return (
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
        {isSearchEmpty ? 'No Results Found' : 'No Chat History Found'}
      </Typography>
      <Typography variant="body1" sx={{ mb: 2 }}>
        {isSearchEmpty
          ? `We couldn't find any chats matching "${searchQuery}".`
          : "We couldn't find any Cursor chat data on your system. This could be because:"}
      </Typography>
      {!isSearchEmpty && (
        <Box sx={{ textAlign: 'left', maxWidth: '600px', mx: 'auto' }}>
          <Typography component="ul" variant="body2" sx={{ mb: 2 }}>
            <li>You haven&apos;t used Cursor&apos;s AI Assistant yet</li>
            <li>Your Cursor databases are stored in a non-standard location</li>
            <li>There might be permission issues accessing the database files</li>
          </Typography>
        </Box>
      )}
      {isSearchEmpty ? (
        <Button
          startIcon={<ClearIcon />}
          onClick={onClearSearch}
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
          onClick={onRetry}
          variant="contained"
          color="primary"
          size="large"
          sx={{ borderRadius: 2 }}
        >
          Retry Detection
        </Button>
      )}
    </Paper>
  );
}
