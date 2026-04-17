import axios from 'axios';

const FORMAT_META = {
  json: { ext: 'json', mime: 'application/json;charset=utf-8' },
  markdown: { ext: 'md', mime: 'text/markdown;charset=utf-8' },
  html: { ext: 'html', mime: 'text/html;charset=utf-8' },
};

function hasDesktopBridge() {
  return (
    typeof window !== 'undefined' &&
    window.pywebview &&
    window.pywebview.api &&
    typeof window.pywebview.api.save_export === 'function'
  );
}

/**
 * Export a chat session.
 *
 * When running inside the pywebview desktop shell, delegate the save to the
 * native Python bridge so a real OS "Save as..." dialog is shown. Otherwise
 * fall back to the standard browser blob + <a download> click pattern.
 *
 * @param {{ sessionId: string, format: 'html'|'json'|'markdown', darkMode: boolean }} params
 * @returns {Promise<{ saved: boolean, cancelled?: boolean, error?: string, path?: string }>}
 */
export async function exportChat({ sessionId, format, darkMode }) {
  const meta = FORMAT_META[format];
  if (!meta) {
    return { saved: false, error: `Unsupported format: ${format}` };
  }

  const theme = darkMode ? 'dark' : 'light';

  if (hasDesktopBridge()) {
    try {
      const result = await window.pywebview.api.save_export(
        sessionId,
        format,
        theme,
      );
      if (!result || typeof result !== 'object') {
        return { saved: false, error: 'Invalid response from desktop bridge' };
      }
      return result;
    } catch (e) {
      return {
        saved: false,
        error: e && e.message ? e.message : String(e),
      };
    }
  }

  try {
    const params = new URLSearchParams({ format, theme });
    const response = await axios.get(
      `/api/chat/${sessionId}/export?${params.toString()}`,
      { responseType: 'blob' },
    );

    const blob = response.data;
    if (!blob || blob.size === 0) {
      return {
        saved: false,
        error: 'Received empty or invalid content from server',
      };
    }

    const typedBlob = blob.type ? blob : new Blob([blob], { type: meta.mime });
    const filename = `cursor-chat-${sessionId.slice(0, 8)}.${meta.ext}`;
    const url = URL.createObjectURL(typedBlob);
    const link = document.createElement('a');
    link.href = url;
    link.download = filename;
    document.body.appendChild(link);
    link.click();
    document.body.removeChild(link);
    URL.revokeObjectURL(url);

    return { saved: true };
  } catch (e) {
    const message = e.response
      ? `Server error: ${e.response.status}`
      : e.request
        ? 'No response received from server'
        : e.message || 'Unknown error setting up request';
    return { saved: false, error: message };
  }
}
