// Module-scope serializer for `mermaid.render` calls. A dark/light
// toggle on a chat with N visible diagrams normally fires N
// `useMermaidRender` effect runs in the same tick (one per
// `MermaidBlock` instance); without this queue, all N
// `mermaid.render` invocations race the JS thread simultaneously
// and the page feels frozen for the union of their durations.
// Routing the renders through a single promise chain runs them one
// at a time, so the JS thread stays interactive between tasks and
// the user sees diagrams update sequentially instead of one big
// freeze.
//
// The queue is consulted **after** the cache check in
// `mermaidRenderCache.js`: a cache hit returns its SVG immediately and
// never enters the queue, so the queue only ever contains genuinely-
// uncached first-paint work for a given `(source, darkMode)` pair.
// Once an entry lands in the cache, all future toggles for that pair
// short-circuit at the cache layer and the queue is empty.
//
// # The chain-vs-result split
//
// The pattern below intentionally forks the returned promise into two
// branches:
//
//   - `result` is what the caller receives. It rejects when the task
//     rejects, so the caller's `await enqueueMermaidRender(...)` /
//     `.catch` continues to see real errors.
//   - `chain` is the queue's internal tail. It is `result.catch(() => {})`,
//     which converts a rejection into a resolved-with-undefined promise.
//     This is what keeps a thrown task from poisoning the queue: the
//     next `enqueueMermaidRender` chains off this swallowing fork, so
//     it runs regardless of whether the previous task succeeded.
//
// Without the swallowing fork, a single task that throws would put
// `chain` into a rejected state forever, and every subsequent enqueue
// would short-circuit with that same rejection. The split keeps caller
// error visibility (real errors propagate to the caller's promise) and
// queue resilience (one bad task doesn't kill the rest) independent.
//
// # Out of scope
//
// The queue is FIFO with concurrency 1. There is no priority lane for
// visible-vs-offscreen diagrams (the IntersectionObserver gate in
// `MermaidDiagramSurface` skips the cross-fade for off-screen
// diagrams, but the underlying render still goes through this queue
// in document order; the user sees on-screen diagrams update first
// in practice because they appear earlier in the DOM). There is also
// no cancellation: a task enqueued by a since-unmounted component
// still runs, but the caller's `latestRef` discriminator inside the
// task body lets it discard the result, and the cache write inside
// the task remains useful for any future remount of the same source.

let chain = Promise.resolve();

export function enqueueMermaidRender(task) {
  const result = chain.then(task);
  chain = result.catch(() => {});
  return result;
}
