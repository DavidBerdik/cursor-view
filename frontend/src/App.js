import React, { useState, useMemo, useEffect } from 'react';
import { BrowserRouter as Router, Routes, Route } from 'react-router-dom';
import { ThemeProvider } from '@mui/material/styles';
import CssBaseline from '@mui/material/CssBaseline';

import ChatList from './components/chat-list/ChatList';
import ChatDetail from './components/chat-detail/ChatDetail';
import Header from './components/Header';
import AppContextMenu from './components/AppContextMenu';
import { ColorContext } from './contexts/ColorContext';
import { ThemeModeContext } from './contexts/ThemeModeContext';
import { buildTheme } from './theme/buildTheme';
import { darkColors, lightColors } from './theme/colors';
import { readThemeCookie, writeThemeCookie } from './theme/themeCookie';

// Disable the browser's built-in scroll restoration so it cannot fire
// during the loading spinner (when the page is too short to reach the saved
// position) and silently reset scroll to 0. ChatDetail owns manual scroll
// restoration via sessionStorage for the chat detail page.
if ('scrollRestoration' in window.history) {
  window.history.scrollRestoration = 'manual';
}

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
