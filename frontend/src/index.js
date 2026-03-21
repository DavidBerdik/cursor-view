import React from 'react';
import ReactDOM from 'react-dom/client';
import App from './App';
import '@wooorm/starry-night/style/core';

// Add global styles
import './index.css';
import './starry-night-theme.css';

const root = ReactDOM.createRoot(document.getElementById('root'));
root.render(
  <React.StrictMode>
    <App />
  </React.StrictMode>
); 