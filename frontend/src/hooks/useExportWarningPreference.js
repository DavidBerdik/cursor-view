import { useEffect, useState } from 'react';

const COOKIE_NAME = 'dontShowExportWarning';

function readPreference() {
  const row = document.cookie
    .split('; ')
    .find((r) => r.startsWith(`${COOKIE_NAME}=`));
  return row ? row.split('=')[1] === 'true' : false;
}

function writePreference(value) {
  const expiry = new Date();
  expiry.setFullYear(expiry.getFullYear() + 1);
  document.cookie = `${COOKIE_NAME}=${value}; expires=${expiry.toUTCString()}; path=/`;
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
