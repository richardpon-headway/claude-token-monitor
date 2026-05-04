import { useEffect, useState } from "react";

interface State {
  refreshKey: number;
  live: boolean;
}

/** Subscribes to /api/stream and exposes a `refreshKey` that bumps on every
 *  SSE push. Also polls /api/usage/windows every 10s as a baseline so the UI
 *  stays current even if SSE drops. `live` reflects current SSE health. */
export function useUsageStream(): State {
  const [refreshKey, setKey] = useState(0);
  const [live, setLive] = useState(false);

  useEffect(() => {
    const bump = () => setKey((k) => k + 1);
    const poll = window.setInterval(bump, 10_000);

    const es = new EventSource("/api/stream");
    es.onopen = () => setLive(true);
    es.onmessage = bump;
    es.onerror = () => setLive(false);

    return () => {
      es.close();
      window.clearInterval(poll);
    };
  }, []);

  return { refreshKey, live };
}
