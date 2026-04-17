// Render a Cursor DB path as the last N path segments joined by "/".
//
// Cursor DB paths look like either ".../User/workspaceStorage/<id>/state.vscdb"
// (workspace DBs) or ".../User/globalStorage/state.vscdb" (global DB), on
// Windows or POSIX. Different pages surface different slices:
//
// - The chat list card shows `<workspace-id>/state.vscdb` (segments: 2)
//   so users can visually differentiate cards coming from different
//   workspace DBs at a glance.
// - The chat detail metadata panel shows just `state.vscdb` (segments: 1,
//   the default) because the full path is already rendered next to it.
//
// Splits on both "/" and "\\" so the same helper works regardless of
// which OS produced the path string.
export function dbPathLabel(dbPath, { segments = 1 } = {}) {
  if (typeof dbPath !== 'string' || !dbPath) {
    return 'Unknown database';
  }
  return dbPath.split(/[\\/]/).slice(-segments).join('/');
}
