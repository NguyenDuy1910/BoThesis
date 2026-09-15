/**
 * A single "something changed, read it again" signal for API-backed views.
 *
 * Views read through `useApiQuery`, which re-runs when this revision moves.
 * Any write that other screens can see — saving a member, switching workspace,
 * uploading a document — calls `invalidateApiData` so the screens showing that
 * data refetch instead of drifting away from the server.
 */

let revision = 0;
const listeners = new Set<() => void>();

export function apiRevision(): number {
  return revision;
}

export function subscribeApiData(listener: () => void): () => void {
  listeners.add(listener);
  return () => {
    listeners.delete(listener);
  };
}

export function invalidateApiData(): void {
  revision += 1;
  for (const listener of listeners) listener();
}
