// Palette constants for the MUI theme. Kept in one place so both the
// light and dark palettes can share a single set of semantic color
// tokens (primary, secondary, info, etc.) and the context defaults in
// `src/contexts/` can import the dark palette as the initial value.

export const sharedColors = {
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

export const darkColors = {
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

export const lightColors = {
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
