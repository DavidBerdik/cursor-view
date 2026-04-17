import React from 'react';
import { IconButton, InputAdornment, TextField } from '@mui/material';
import ClearIcon from '@mui/icons-material/Clear';
import SearchIcon from '@mui/icons-material/Search';

export default function SearchBar({ value, onChange, onClear }) {
  return (
    <TextField
      fullWidth
      variant="outlined"
      placeholder="Search by project name or chat content..."
      value={value}
      onChange={onChange}
      size="medium"
      sx={{ mb: 3 }}
      InputProps={{
        startAdornment: (
          <InputAdornment position="start">
            <SearchIcon color="action" />
          </InputAdornment>
        ),
        endAdornment: value && (
          <InputAdornment position="end">
            <IconButton
              size="small"
              aria-label="clear search"
              onClick={onClear}
              edge="end"
            >
              <ClearIcon />
            </IconButton>
          </InputAdornment>
        ),
        sx: { borderRadius: 2 },
      }}
    />
  );
}
