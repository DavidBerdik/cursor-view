import { useLayoutEffect } from 'react';

// Save and restore the chat-detail scroll position across refreshes
// and per-session navigations. Owns the entire restore-then-track
// state machine that previously lived inline in `ChatDetail.js`'s
// `useLayoutEffect`; extracted here per `react-components.mdc`
// "Component size and layout" once `ChatDetail.js` crossed the
// ~250-line cap with the anchor-based save and the rAF re-scroll
// loop landing in the same change. Mirrors `useSavedSelection`'s
// shape (DOM-state save/restore + rAF chain) catalogued in
// `frontend-hooks.mdc` "DOM selection save/restore".
//
// Save / restore is anchor-based: instead of persisting a raw
// `window.scrollY`, we record the topmost in-viewport message
// bubble's index plus the user's vertical offset within it
// (`{ msgIdx, offset }` JSON in `sessionStorage`). At restore time
// we recompute scrollY from the anchor's current `offsetTop` plus
// the saved offset. Anchoring to a specific message absorbs any
// layout-shift between save and restore: any size delta in
// elements above the anchor moves the anchor's `offsetTop` by
// exactly the same amount, so `offsetTop + offset` lands on the
// same visual position within the anchor.
//
// On chats with mermaid diagrams the layout determinism comes from
// `useMermaidBlockHeight` + `mermaidHeightCache`: each
// `MermaidBlock`'s outer `<Box>` carries `contentVisibility: 'auto'`
// + a `containIntrinsicSize` derived from the block's last-recorded
// rendered height (persisted in `sessionStorage` by a
// `ResizeObserver`), so off-screen blocks reserve their actual
// height as the placeholder rather than the legacy static 400px
// heuristic. With placeholders matching actual heights, the
// anchor's `offsetTop` is correct on first measurement here. The
// rAF re-scroll loop below is the safety net for the residual case
// where a block's height has not been recorded yet (first-ever
// load, sessionStorage unavailable, or a source the user scrolled
// past too fast for the observer to fire) -- it converges on
// chats where every block above the anchor is already measured,
// and chases the cascade on the rare unmeasured-block path.
//
// `useLayoutEffect` (not `useEffect`) is load-bearing: it fires
// after React commits the DOM but before the browser paints, so
// the initial `scrollTo` executes before the first frame is drawn
// and the user never sees a flash at position 0. Pair this with
// `window.history.scrollRestoration = 'manual'` at the App level
// so the browser's own restore attempt cannot fire during the
// loading spinner and clobber the position we set here.
//
// Two fallbacks: a legacy plain-number entry (existing user
// `sessionStorage` from before the anchor format landed) restores
// via the original `Number(raw)` path; a JSON entry whose `msgIdx`
// no longer exists in the DOM (e.g. a chat that lost messages)
// restores to the top, which is safer than scrolling to a stale
// absolute scrollY that no longer corresponds to anything in the
// new layout.
//
// Hook ignores the effect entirely while `ready` is false so the
// caller's "data still loading" state cleanly suppresses any
// restore attempt against a half-mounted DOM.
export function useChatScrollAnchor(sessionId, ready) {
  useLayoutEffect(() => {
    if (!ready) {
      return undefined;
    }

    const key = `scroll-chat-${sessionId}`;
    // `sessionStorage` access can throw under storage-disabled browser
    // settings, some enterprise lockdowns, or quota exceeded; mirror
    // `mermaidHeightCache.js`'s defensive shape and degrade silently
    // to "no saved entry" rather than crash the chat-detail mount.
    let raw;
    try {
      raw = sessionStorage.getItem(key);
    } catch {
      raw = null;
    }
    let targetY = 0;
    let stabilizationData = null;
    if (raw !== null) {
      try {
        const parsed = JSON.parse(raw);
        if (typeof parsed === 'number') {
          targetY = parsed;
        } else if (parsed && typeof parsed === 'object' && typeof parsed.msgIdx === 'number') {
          const anchorEl = document.querySelector(`[data-msg-idx="${parsed.msgIdx}"]`);
          if (anchorEl !== null) {
            const offset = typeof parsed.offset === 'number' ? parsed.offset : 0;
            targetY = anchorEl.offsetTop + offset;
            stabilizationData = { msgIdx: parsed.msgIdx, offset };
          }
        }
      } catch {
        targetY = Number(raw) || 0;
      }
    }
    window.scrollTo(0, targetY);

    // Safety net for the residual case where a `MermaidBlock` above
    // the anchor lacks a persisted height entry: its outer `<Box>`
    // falls through to the static 400px `containIntrinsicSize`
    // placeholder, and `content-visibility: auto` materializes the
    // block on the next paint after the `scrollTo` above brings it
    // into the viewport buffer -- shifting `anchor.offsetTop` by the
    // actual-vs-400px delta while `scrollY` stays put. Each rAF
    // iteration re-reads the anchor's `offsetTop` and re-scrolls
    // when the recomputed target differs from the current `scrollY`
    // by more than the 1-px tolerance (the tolerance prevents a
    // no-op `scrollTo` from re-triggering layout work).
    //
    // Convergence rule: exit after the position is STABLE for two
    // consecutive frames (one stable frame can be a false negative
    // if `content-visibility` re-evaluation is still pending in the
    // browser's rendering update; two stable frames means the
    // cascade has fully propagated). The `SAFETY_CAP_FRAMES` ceiling
    // guards against a pathological cascade that never settles --
    // 30 frames is a generous bound the typical case (with all
    // heights persisted) reaches in zero or one frame.
    //
    // Skipped entirely for the legacy plain-number fallback, the
    // no-saved-entry path, and the JSON-with-missing-anchor path
    // because there is no anchor to stabilize against.
    let stabilizationRafId = null;
    if (stabilizationData !== null) {
      const STABLE_FRAMES_REQUIRED = 2;
      const SAFETY_CAP_FRAMES = 30;
      let frame = 0;
      let stableFrames = 0;
      const tryStabilize = () => {
        stabilizationRafId = null;
        if (frame >= SAFETY_CAP_FRAMES) {
          return;
        }
        frame += 1;
        const anchorEl = document.querySelector(
          `[data-msg-idx="${stabilizationData.msgIdx}"]`,
        );
        if (anchorEl === null) {
          return;
        }
        const newTargetY = anchorEl.offsetTop + stabilizationData.offset;
        if (Math.abs(newTargetY - window.scrollY) > 1) {
          window.scrollTo(0, newTargetY);
          stableFrames = 0;
        } else {
          stableFrames += 1;
          if (stableFrames >= STABLE_FRAMES_REQUIRED) {
            return;
          }
        }
        stabilizationRafId = requestAnimationFrame(tryStabilize);
      };
      stabilizationRafId = requestAnimationFrame(tryStabilize);
    }

    let saveTimer;
    function handleScroll() {
      clearTimeout(saveTimer);
      saveTimer = setTimeout(() => {
        // Topmost in-viewport bubble: the first `[data-msg-idx]`
        // whose bottom edge is below the viewport top. If no bubble
        // intersects the viewport (very short chat scrolled past end,
        // empty chat), persist the raw scrollY so the legacy restore
        // path picks it up next load.
        const els = document.querySelectorAll('[data-msg-idx]');
        let anchor = null;
        for (const el of els) {
          if (el.getBoundingClientRect().bottom > 0) {
            anchor = el;
            break;
          }
        }
        // Same defensive try/catch shape as the read above: on a
        // throw we lose the unsaved scroll position for this debounce
        // tick, which is acceptable degradation -- the page itself
        // keeps functioning.
        if (anchor === null) {
          try {
            sessionStorage.setItem(key, String(window.scrollY));
          } catch {
            /* storage unavailable; drop this save */
          }
          return;
        }
        const msgIdx = Number(anchor.dataset.msgIdx);
        const offset = window.scrollY - anchor.offsetTop;
        try {
          sessionStorage.setItem(key, JSON.stringify({ msgIdx, offset }));
        } catch {
          /* storage unavailable; drop this save */
        }
      }, 150);
    }

    window.addEventListener('scroll', handleScroll, { passive: true });

    return () => {
      if (stabilizationRafId !== null) {
        cancelAnimationFrame(stabilizationRafId);
      }
      clearTimeout(saveTimer);
      window.removeEventListener('scroll', handleScroll);
    };
  }, [ready, sessionId]);
}
