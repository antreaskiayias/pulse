import axios from "axios";

const API_URL = import.meta.env.VITE_API_URL;

export interface Candle {
  bucket: string;
  open: number;
  high: number;
  low: number;
  close: number;
  volume: number;
  trade_count: number;
}

export interface OhlcResponse {
  symbol: string;
  interval: string;
  candles: Candle[];
}

export interface TopSymbol {
  symbol: string;
  volume_quote: number;
  trade_count: number;
}

export async function fetchSymbols(): Promise<string[]> {
  const res = await axios.get<{ symbols: string[] }>(`${API_URL}/symbols`);
  return res.data.symbols;
}

export async function fetchOhlc(
  symbol: string,
  interval: string = "1m",
  limit: number = 60
): Promise<OhlcResponse> {
  const res = await axios.get<OhlcResponse>(`${API_URL}/ohlc`, {
    params: { symbol, interval, limit },
  });
  return res.data;
}

export async function fetchTopSymbols(
  windowMinutes: number = 5,
  limit: number = 10
): Promise<{ window_minutes: number; top_symbols: TopSymbol[] }> {
  const res = await axios.get(`${API_URL}/top-symbols`, {
    params: { window_minutes: windowMinutes, limit },
  });
  return res.data;
}
