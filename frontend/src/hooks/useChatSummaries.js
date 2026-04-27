import { startTransition, useCallback, useEffect, useRef, useState } from 'react';
import axios from 'axios';

// GET /api/chats with optional query filter and cache-bust flag.
// ``signal`` lets callers cancel the in-flight request when the
// query changes or the component unmounts; without it, a slow
// response from a stale prefix would still occupy the Flask worker
// even though the frontend ignores the result.
async function fetchChatSummaries(query, refresh = false, signal = undefined) {
  const params = new URLSearchParams();
  if (query) {
    params.set('q', query);
  }
  if (refresh) {
    params.set('refresh', '1');
  }
  const suffix = params.toString() ? `?${params.toString()}` : '';
  const response = await axios.get(`/api/chats${suffix}`, { signal });
  return response.data;
}

// Owns the chat summary list state driven by a (typically debounced)
// search query.
//
// - Re-fetches whenever ``query`` changes, aborting any in-flight
//   request via ``AbortController`` so a slow response from an older
//   prefix can never overwrite the fresh result. The ``latestRef``
//   token is the canonical pattern from
//   ``.cursor/rules/frontend-hooks.mdc``: bumped at the start of the
//   effect and of ``refresh()``, checked after every ``await``
//   boundary so both code paths participate in the same gating.
// - Commits the payload inside ``startTransition`` so the empty-state
//   does not flash while React is still reconciling the new list.
// - ``refresh()`` forces a cache-busting re-fetch against the same
//   ``query`` the caller passed in, and is used by the manual
//   Refresh button in the page header.
//
// Returns ``{ chatData, loading, error, refresh }``.
export function useChatSummaries(query) {
  const [chatData, setChatData] = useState({ items: [], total: 0 });
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const latestRef = useRef(0);
  const abortRef = useRef(null);

  const applyPayload = (payload) => {
    // Keep setLoading(false) inside the same transition as setChatData so React
    // never commits loading=false while items are still empty (avoids empty-state flash).
    startTransition(() => {
      setChatData({
        items: Array.isArray(payload.items) ? payload.items : [],
        total: Number.isFinite(payload.total) ? payload.total : 0,
      });
      setLoading(false);
    });
  };

  useEffect(() => {
    const requestId = ++latestRef.current;
    if (abortRef.current) {
      abortRef.current.abort();
    }
    const controller = new AbortController();
    abortRef.current = controller;

    setLoading(true);
    setError(null);

    fetchChatSummaries(query, false, controller.signal)
      .then((payload) => {
        if (requestId !== latestRef.current) {
          return;
        }
        applyPayload(payload);
      })
      .catch((err) => {
        if (axios.isCancel?.(err) || err?.name === 'CanceledError' || err?.name === 'AbortError') {
          return;
        }
        if (requestId !== latestRef.current) {
          return;
        }
        setError(err.message);
        setLoading(false);
      });

    return () => {
      controller.abort();
    };
  }, [query]);

  const refresh = useCallback(async () => {
    const requestId = ++latestRef.current;
    if (abortRef.current) {
      abortRef.current.abort();
    }
    const controller = new AbortController();
    abortRef.current = controller;

    setLoading(true);
    setError(null);
    try {
      const payload = await fetchChatSummaries(query, true, controller.signal);
      if (requestId !== latestRef.current) {
        return;
      }
      applyPayload(payload);
    } catch (err) {
      if (axios.isCancel?.(err) || err?.name === 'CanceledError' || err?.name === 'AbortError') {
        return;
      }
      if (requestId !== latestRef.current) {
        return;
      }
      setError(err.message);
      setLoading(false);
    }
  }, [query]);

  return { chatData, loading, error, refresh };
}
