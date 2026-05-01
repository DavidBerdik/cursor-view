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
// the saved offset. This is robust to layout changes between save
// and restore -- specifically, `MermaidBlock`'s `contentVisibility:
// 'auto'` + `containIntrinsicSize: '0 400px'` pair gives every
// off-screen mermaid block a 400px placeholder height that does
// not match the actual rendered diagram height. A raw scrollY
// save/restore drifts because every materialized-then-de-materialized
// mermaid block above the viewport changes total page height
// between save (some blocks materialized) and restore (all
// off-screen blocks at the 400px placeholder). Anchoring to a
// specific message absorbs that drift: any size delta in mermaid
// blocks above the anchor moves the anchor's `offsetTop` by exactly
// the same amount, so `offsetTop + offset` lands on the same
// visual position within the anchor.
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
    const raw = sessionStorage.getItem(key);
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

    // `content-visibility: auto` on every off-screen `MermaidBlock`
    // skips layout/paint at the 400px placeholder until the block
    // enters the viewport buffer; the `scrollTo` above causes the
    // browser to re-evaluate that, materializing blocks now in or
    // near the new viewport on the next paint and shifting
    // `anchor.offsetTop` while `scrollY` stays put. Chase that shift
    // via rAF: each iteration re-reads the anchor's `offsetTop` and
    // re-scrolls if it differs from the current `scrollY` by more
    // than the 1-px tolerance (which prevents a no-op `scrollTo`
    // from re-triggering layout work). 5-frame cap is a safety net
    // against a pathological materialization cascade; in practice
    // 2-3 frames are enough. Skipped entirely for the legacy plain-
    // number fallback and the no-saved-entry / anchor-missing paths
    // because there is no anchor to stabilize against.
    let stabilizationRafId = null;
    if (stabilizationData !== null) {
      let frame = 0;
      const MAX_STABILIZATION_FRAMES = 5;
      const tryStabilize = () => {
        stabilizationRafId = null;
        if (frame >= MAX_STABILIZATION_FRAMES) {
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
        if (anchor === null) {
          sessionStorage.setItem(key, String(window.scrollY));
          return;
        }
        const msgIdx = Number(anchor.dataset.msgIdx);
        const offset = window.scrollY - anchor.offsetTop;
        sessionStorage.setItem(key, JSON.stringify({ msgIdx, offset }));
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
