// Render a timestamp into a user-friendly localized string.
//
// Accepts the Unix-seconds number shape the API returns (e.g.
// 1734310800). Returns "Unknown date" for any falsy or non-parseable
// input rather than throwing, so callers can render the result
// directly without guards.
export function formatDate(date) {
  try {
    if (!date) {
      return 'Unknown date';
    }
    const dateObject = new Date(date * 1000);
    if (Number.isNaN(dateObject.getTime())) {
      return 'Unknown date';
    }
    return dateObject.toLocaleString();
  } catch {
    return 'Unknown date';
  }
}
