import { startTransition, useEffect, useState } from 'react';
import axios from 'axios';

// GET /api/chats with optional query filter and cache-bust flag.
async function fetchChatSummaries(query, refresh = false) {
  const params = new URLSearchParams();
  if (query) {
    params.set('q', query);
  }
  if (refresh) {
    params.set('refresh', '1');
  }
  const suffix = params.toString() ? `?${params.toString()}` : '';
  const response = await axios.get(`/api/chats${suffix}`);
  return response.data;
}

// Owns the chat summary list state driven by a deferred search query.
//
// - Re-fetches (cancelling any in-flight request) whenever `query`
//   changes, commits the payload inside `startTransition` so the
//   empty-state doesn't flash while React is still reconciling.
// - `refresh()` forces a cache-busting re-fetch against the same
//   `query` the caller passed in, and is used by the manual Refresh
//   button in the page header.
//
// Returns `{ chatData, loading, error, refresh }`.
export function useChatSummaries(query) {
  const [chatData, setChatData] = useState({ items: [], total: 0 });
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);

  useEffect(() => {
    let cancelled = false;

    setLoading(true);
    setError(null);

    fetchChatSummaries(query)
      .then((payload) => {
        if (cancelled) {
          return;
        }
        // Keep setLoading(false) inside the same transition as setChatData so React
        // never commits loading=false while items are still empty (avoids empty-state flash).
        startTransition(() => {
          setChatData({
            items: Array.isArray(payload.items) ? payload.items : [],
            total: Number.isFinite(payload.total) ? payload.total : 0,
          });
          setLoading(false);
        });
      })
      .catch((err) => {
        if (cancelled) {
          return;
        }
        setError(err.message);
        setLoading(false);
      });

    return () => {
      cancelled = true;
    };
  }, [query]);

  const refresh = async () => {
    setLoading(true);
    setError(null);
    try {
      const payload = await fetchChatSummaries(query, true);
      startTransition(() => {
        setChatData({
          items: Array.isArray(payload.items) ? payload.items : [],
          total: Number.isFinite(payload.total) ? payload.total : 0,
        });
        setLoading(false);
      });
    } catch (err) {
      setError(err.message);
      setLoading(false);
    }
  };

  return { chatData, loading, error, refresh };
}
