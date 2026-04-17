import { useEffect, useState } from 'react';

import { getCookie, oneYearFromNow, setCookie } from '../utils/cookies';

const COOKIE_NAME = 'dontShowExportWarning';

function readPreference() {
  return getCookie(COOKIE_NAME) === 'true';
}

function writePreference(value) {
  setCookie(COOKIE_NAME, value, { expires: oneYearFromNow() });
}

// Encapsulates the ``dontShowExportWarning`` cookie that the export
// warning dialog reads + writes. Exposes the current value, a React
// setter the checkbox binds to, and a ``persist()`` helper callers
// invoke when the user resolves the warning dialog. Splitting reading
// (on mount) from writing (on dialog close) mirrors how the feature was
// implemented inline on each page before this hook existed.
export function useExportWarningPreference() {
  const [dontShow, setDontShow] = useState(false);

  useEffect(() => {
    setDontShow(readPreference());
  }, []);

  const persist = () => writePreference(dontShow);

  return { dontShow, setDontShow, persist };
}
