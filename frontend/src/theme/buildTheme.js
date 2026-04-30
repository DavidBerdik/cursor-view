import { createTheme } from '@mui/material/styles';

import { darkColors, lightColors } from './colors';
import { PALETTE_TRANSITION } from './transitions';

// `colors.js` exports `highlightColor` as a top-level field on each
// scheme rather than a palette token. MUI palette tokens look like
// `{ main, light, dark }`, and only that shape gets a corresponding
// `--mui-palette-X-main` CSS variable from `createTheme`'s
// CSS-variables generator. The lift here is what lets
// `MuiCircularProgress`, `MuiButton`, etc. reference
// `var(--mui-palette-highlight-main)` below and have the browser
// swap the value automatically when `data-mui-color-scheme` flips.
function paletteFromColors(c) {
  return {
    primary: c.primary,
    secondary: c.secondary,
    background: c.background,
    text: c.text,
    info: c.info,
    success: c.success,
    warning: c.warning,
    error: c.error,
    highlight: { main: c.highlightColor },
  };
}

// Build the single static MUI theme used app-wide. Migrated from
// `createTheme(c, mode)` (one theme per scheme, rebuilt by App.js's
// `useMemo` on every dark/light toggle) to a single
// `createTheme({ cssVariables, colorSchemes: { light, dark } })`
// with both schemes baked in. The dark/light flip becomes a CSS-only
// operation on the `data-mui-color-scheme` attribute set by MUI's
// CSS-variables-aware `ThemeProvider` (App.js): no React re-render
// of palette consumers, no theme rebuild, just the browser
// recomputing styles for elements that reference
// `var(--mui-palette-*)`.
//
// Two pieces of the `cssVariables` config are load-bearing:
//
// 1. The config object's mere presence (any truthy value) gates
//    whether MUI emits CSS variables to the document at all.
//    Without it the `colorSchemes` config is accepted but no
//    `--mui-palette-*` variables are generated, and the `var(...)`
//    references in the component `styleOverrides` below resolve to
//    the CSS-variable fallback (i.e. nothing).
// 2. `colorSchemeSelector: 'data-mui-color-scheme'` overrides MUI 7's
//    default-when-both-schemes-are-defined behavior, which is `'media'`
//    (variables flip on `prefers-color-scheme`, the OS preference).
//    Under `'media'`, our toggle button writes `data-mui-color-scheme`
//    via `setMode` but the CSS variables stay glued to the OS theme,
//    so the visible UI is stuck while `useColorScheme().mode` (and
//    therefore the `darkMode` boolean consumers like mermaid's
//    `theme: darkMode ? 'dark' : 'default'`) flips correctly. The
//    bug expresses as "mermaid charts switch theme but everything
//    else does not" -- a subtle failure mode because half the app
//    appears to work.
//
// MUI 7 deprecated the older `extendTheme` + `CssVarsProvider` pair
// in favor of this `createTheme({ cssVariables, colorSchemes })`
// pattern; the configuration docs are at
// https://mui.com/material-ui/customization/css-theme-variables/configuration/.
//
// Parameterless on purpose. The previous `(c, mode)` arguments
// selected a scheme at build time; with both schemes inside one
// theme, the active scheme is picked at emit time by the provider
// (`defaultMode` + `useColorScheme().setMode`).
//
// Component `styleOverrides` reference palette tokens via CSS
// variables (`var(--mui-palette-X)`) rather than scheme-specific
// hex literals interpolated from a `c` argument. A single
// styleOverride definition serves both schemes this way -- the
// browser substitutes the active scheme's value at use-site
// whenever `data-mui-color-scheme` flips.
//
// `transition: PALETTE_TRANSITION` styleOverrides stay as-is. View
// Transitions (`App.js::toggleDarkMode`) replaces these as the
// *primary* theme-fade mechanism on supporting browsers, but per-
// element transitions remain the fallback path for unsupported
// browsers and continue to cover non-toggle palette changes (focus
// and hover state). Dropping them would regress those cases.
export function buildTheme() {
  return createTheme({
    cssVariables: {
      colorSchemeSelector: 'data-mui-color-scheme',
    },
    colorSchemes: {
      light: { palette: paletteFromColors(lightColors) },
      dark: { palette: paletteFromColors(darkColors) },
    },
    typography: {
      fontFamily: "'Inter', 'Roboto', 'Helvetica', 'Arial', sans-serif",
      h4: { fontWeight: 700 },
      h5: { fontWeight: 600 },
    },
    shape: { borderRadius: 10 },
    components: {
      MuiCssBaseline: {
        styleOverrides: {
          // The full-page background and default text color come from
          // MUI's `CssBaseline` reset writing `background-color:
          // theme.palette.background.default` and `color:
          // theme.palette.text.primary` directly on the body element.
          // Without this transition, the single largest surface in the
          // UI flashes from light to dark on every toggle while the
          // surrounding chrome (already covered by the per-component
          // overrides below) fades. Centralizing it here means no
          // component needs to know that `<body>` is special.
          body: {
            transition: PALETTE_TRANSITION,
          },
        },
      },
      MuiCard: {
        styleOverrides: {
          root: {
            borderRadius: 10,
            boxShadow: '0 4px 10px var(--mui-palette-highlight-main)',
            backgroundColor: 'var(--mui-palette-background-paper)',
            transition: PALETTE_TRANSITION,
          },
        },
      },
      MuiPaper: {
        styleOverrides: {
          root: {
            borderRadius: 10,
            backgroundColor: 'var(--mui-palette-background-paper)',
            transition: PALETTE_TRANSITION,
          },
        },
      },
      MuiAppBar: {
        styleOverrides: {
          root: {
            background: 'var(--mui-palette-primary-dark)',
            borderRadius: 0,
            transition: PALETTE_TRANSITION,
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
            transition: PALETTE_TRANSITION,
          },
          contained: {
            boxShadow: '0 2px 4px var(--mui-palette-highlight-main)',
            color: 'white',
          },
          outlined: {
            borderColor: 'var(--mui-palette-highlight-main)',
            '&:hover': { borderColor: 'var(--mui-palette-highlight-main)' },
          },
        },
      },
      MuiChip: {
        styleOverrides: { root: { borderRadius: 4, transition: PALETTE_TRANSITION } },
      },
      MuiCircularProgress: {
        styleOverrides: { root: { color: 'var(--mui-palette-highlight-main)' } },
      },
      // Transition-only overrides: these MUI components carry no other
      // theme customization, but their default palette-derived colors
      // (`text.primary` / `text.secondary` / `divider` / etc.) flash on
      // dark/light toggle without an explicit `transition`. Grouped at
      // the end of the components map so the customization-bearing
      // entries above stay readable.
      MuiAvatar: {
        styleOverrides: { root: { transition: PALETTE_TRANSITION } },
      },
      MuiDivider: {
        styleOverrides: { root: { transition: PALETTE_TRANSITION } },
      },
      MuiIconButton: {
        styleOverrides: { root: { transition: PALETTE_TRANSITION } },
      },
      MuiOutlinedInput: {
        styleOverrides: { root: { transition: PALETTE_TRANSITION } },
      },
      MuiSvgIcon: {
        styleOverrides: { root: { transition: PALETTE_TRANSITION } },
      },
      MuiTypography: {
        styleOverrides: { root: { transition: PALETTE_TRANSITION } },
      },
    },
  });
}
