import { createContext } from 'react';

import { darkColors } from '../theme/colors';

// Exposes the current-mode color palette to descendants. Default value
// is the dark palette so consumers outside the <ColorContext.Provider>
// (e.g. stray dev-tools previews) still render with a sensible theme.
export const ColorContext = createContext(darkColors);
