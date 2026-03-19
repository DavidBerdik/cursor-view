import React, { useContext } from 'react';
import { Link } from 'react-router-dom';
import { AppBar, Toolbar, Typography, Box, Container, Button, IconButton, Tooltip } from '@mui/material';
import ChatIcon from '@mui/icons-material/Chat';
import GitHubIcon from '@mui/icons-material/GitHub';
import DarkModeIcon from '@mui/icons-material/DarkMode';
import LightModeIcon from '@mui/icons-material/LightMode';
import { ColorContext, ThemeModeContext } from '../App';

const Header = () => {
  const colors = useContext(ColorContext);
  const { darkMode, toggleDarkMode } = useContext(ThemeModeContext);

  return (
    <AppBar position="sticky" sx={{ mb: 4, color: 'white' }}>
      <Container>
        <Toolbar sx={{ p: { xs: 1, sm: 1.5 }, px: { xs: 1, sm: 0 } }}>
          <Box component={Link} to="/" sx={{ 
            display: 'flex', 
            alignItems: 'center', 
            textDecoration: 'none', 
            color: 'inherit',
            flexGrow: 1,
            '&:hover': {
              textDecoration: 'none'
            }
          }}>
            <ChatIcon sx={{ mr: 1.5, fontSize: 28 }} />
            <Typography variant="h5" component="div" fontWeight="700">
              Cursor View
            </Typography>
          </Box>

          <Tooltip title={darkMode ? 'Switch to light mode' : 'Switch to dark mode'}>
            <IconButton
              onClick={toggleDarkMode}
              color="inherit"
              sx={{ mr: 1 }}
            >
              {darkMode ? <LightModeIcon /> : <DarkModeIcon />}
            </IconButton>
          </Tooltip>
          
          <Button 
            component="a"
            href="https://github.com/DavidBerdik/cursor-view"
            target="_blank"
            rel="noopener noreferrer"
            startIcon={<GitHubIcon />}
            variant="outlined"
            color="inherit"
            size="small"
            sx={{ 
              borderColor: 'rgba(255,255,255,0.5)', 
              '&:hover': { 
                borderColor: 'rgba(255,255,255,0.8)',
                backgroundColor: colors.highlightColor
              }
            }}
          >
            GitHub
          </Button>
        </Toolbar>
      </Container>
    </AppBar>
  );
};

export default Header; 