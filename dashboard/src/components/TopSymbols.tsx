import { fetchTopSymbols } from "../api";
import { usePolling } from "../hooks/usePolling";

interface Props {
  onSelectSymbol: (symbol: string) => void;
}

export default function TopSymbols({ onSelectSymbol }: Props) {
  const { data, error } = usePolling(() => fetchTopSymbols(5, 10), 5000, []);

  if (error) return <div className="error">Failed to load: {error}</div>;
  if (!data) return <div>Loading...</div>;

  return (
    <div>
      <h3>Top Symbols (5m volume)</h3>
      <table style={{ width: "100%", borderCollapse: "collapse" }}>
        <thead>
          <tr>
            <th style={{ textAlign: "left" }}>Symbol</th>
            <th style={{ textAlign: "right" }}>Quote Volume</th>
            <th style={{ textAlign: "right" }}>Trades</th>
          </tr>
        </thead>
        <tbody>
          {data.top_symbols.map((s) => (
            <tr
              key={s.symbol}
              onClick={() => onSelectSymbol(s.symbol)}
              style={{ cursor: "pointer" }}
              title="Click to view this symbol"
            >
              <td>{s.symbol}</td>
              <td style={{ textAlign: "right" }}>{s.volume_quote.toLocaleString(undefined, { maximumFractionDigits: 0 })}</td>
              <td style={{ textAlign: "right" }}>{s.trade_count}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
