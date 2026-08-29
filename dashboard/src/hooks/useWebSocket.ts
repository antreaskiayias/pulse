import { useEffect, useState } from "react";

export function usePhaseSpace<T = unknown>(symbol: string): T | null {
  const [data, setData] = useState<T | null>(null);

  useEffect(() => {
    const wsUrl = import.meta.env.VITE_API_URL.replace("http", "ws");
    const ws = new WebSocket(`${wsUrl}/ws/tda/${symbol}`);
    ws.onmessage = (event) => setData(JSON.parse(event.data));
    return () => ws.close();
  }, [symbol]);

  return data;
}
