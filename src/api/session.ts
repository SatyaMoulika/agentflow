import { useSyncExternalStore } from 'react';
import { client } from './client';
export function useSession() {
  return useSyncExternalStore(client.subscribe, client.snapshot, client.snapshot);
}

export function useScope() {
  const session = useSession();
  return [session.user?.id || 'anonymous', session.generation] as const;
}
