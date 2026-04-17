import React, { useState, useMemo, useEffect, createContext } from 'react';
import { BrowserRouter as Router, Routes, Route } from 'react-router-dom';
import { ThemeProvider, createTheme } from '@mui/material/styles';
import CssBaseline from '@mui/material/CssBaseline';

import ChatList from './components/ChatList';
import ChatDetail from './components/ChatDetail';
import Header from './components/Header';
import AppContextMenu from './components/AppContextMenu';

const sharedColors = {
  primary: {
    main: '#00bbff',
    light: '#66d6ff',
    dark: '#005e80',
  },
  secondary: {
    main: '#FF6B35',
    light: '#FF8F5E',
    dark: '#E04F1D',
  },
  tertiary: {
    main: '#3EBD64',
    light: '#5FD583',
    dark: '#2A9E4A',
  },
  info:    { main: '#39C0F7' },
  success: { main: '#3EBD64' },
  warning: { main: '#FAAD14' },
  error:   { main: '#F5222D' },
};

const darkColors = {
  ...sharedColors,
  highlightColor: '#0cbcff8f',
  background: {
    default: '#121212',
    paper: '#1E1E1E',
  },
  text: {
    primary: '#FFFFFF',
    secondary: '#B3B3B3',
  },
};

const lightColors = {
  ...sharedColors,
  highlightColor: '#0097cc',
  background: {
    default: '#f5f5f5',
    paper: '#ffffff',
  },
  text: {
    primary: '#1a1a1a',
    secondary: '#666666',
  },
};

function readThemeCookie() {
  const match = document.cookie
    .split('; ')
    .find((r) => r.startsWith('themeMode='));
  return match ? match.split('=')[1] !== 'light' : true;
}

function writeThemeCookie(isDark) {
  const expiry = new Date();
  expiry.setFullYear(expiry.getFullYear() + 1);
  document.cookie = `themeMode=${isDark ? 'dark' : 'light'}; expires=${expiry.toUTCString()}; path=/`;
}

function buildTheme(c, mode) {
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

export const ColorContext = createContext(darkColors);
export const ThemeModeContext = createContext({
  darkMode: true,
  toggleDarkMode: () => {},
});

function App() {
  const [darkMode, setDarkMode] = useState(readThemeCookie);

  useEffect(() => {
    document.documentElement.dataset.theme = darkMode ? 'dark' : 'light';
  }, [darkMode]);

  const toggleDarkMode = () => {
    setDarkMode((prev) => {
      const next = !prev;
      writeThemeCookie(next);
      return next;
    });
  };

  const activeColors = darkMode ? darkColors : lightColors;
  const theme = useMemo(
    () => buildTheme(activeColors, darkMode ? 'dark' : 'light'),
    [darkMode, activeColors],
  );

  return (
    <ThemeModeContext.Provider value={{ darkMode, toggleDarkMode }}>
      <ColorContext.Provider value={activeColors}>
        <ThemeProvider theme={theme}>
          <CssBaseline />
          <Router>
            <Header />
            <AppContextMenu />
            <Routes>
              <Route path="/" element={<ChatList />} />
              <Route path="/chat/:sessionId" element={<ChatDetail />} />
            </Routes>
          </Router>
        </ThemeProvider>
      </ColorContext.Provider>
    </ThemeModeContext.Provider>
  );
}

export default App; 