import { createTheme } from '@mui/material/styles';

// Build a fully-configured MUI theme for either light or dark mode. The
// color palette (`c`) is one of the exports from ./colors; `mode` is the
// MUI palette mode ('light' | 'dark'). Kept as a pure function so
// App.js can memoize the result on (c, mode).
export function buildTheme(c, mode) {
  return createTheme({
    palette: {
      mode,
      primary: c.primary,
      secondary: c.secondary,
      background: c.background,
      text: c.text,
      info: c.info,
      success: c.success,
      warning: c.warning,
      error: c.error,
      highlight: { main: c.highlightColor },
    },
    typography: {
      fontFamily: "'Inter', 'Roboto', 'Helvetica', 'Arial', sans-serif",
      h4: { fontWeight: 700 },
      h5: { fontWeight: 600 },
    },
    shape: { borderRadius: 10 },
    components: {
      MuiCard: {
        styleOverrides: {
          root: {
            borderRadius: 10,
            boxShadow: `0 4px 10px ${c.highlightColor}`,
            backgroundColor: c.background.paper,
          },
        },
      },
      MuiPaper: {
        styleOverrides: {
          root: {
            borderRadius: 10,
            backgroundColor: c.background.paper,
          },
        },
      },
      MuiAppBar: {
        styleOverrides: {
          root: {
            background: c.primary.dark,
            borderRadius: 0,
          },
        },
      },
      MuiTextField: {
        styleOverrides: {
          root: {
            '& .MuiOutlinedInput-root': {
              backgroundColor: 'transparent',
              '&:hover': { backgroundColor: 'transparent' },
              '&.Mui-focused': { backgroundColor: 'transparent' },
            },
          },
        },
      },
      MuiButton: {
        styleOverrides: {
          root: {
            textTransform: 'none',
            borderRadius: 6,
            fontWeight: 500,
          },
          contained: {
            boxShadow: `0 2px 4px ${c.highlightColor}`,
            color: 'white',
          },
          outlined: {
            borderColor: c.highlightColor,
            '&:hover': { borderColor: c.highlightColor },
          },
        },
      },
      MuiChip: {
        styleOverrides: { root: { borderRadius: 4 } },
      },
      MuiCircularProgress: {
        styleOverrides: { root: { color: c.highlightColor } },
      },
    },
  });
}
