import { LineChart, Line, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer } from "recharts";
import { fetchOhlc } from "../api";
import { usePolling } from "../hooks/usePolling";

interface Props {
  symbol: string;
  interval: string;
}

export default function PriceChart({ symbol, interval }: Props) {
  const { data, error } = usePolling(
    () => fetchOhlc(symbol, interval, 60),
    3000,
    [symbol, interval]
  );

  if (error) return <div className="error">Failed to load: {error}</div>;
  if (!data) return <div>Loading...</div>;

  const chartData = data.candles.map((c) => ({
    time: new Date(c.bucket).toLocaleTimeString(),
    close: c.close,
    volume: c.volume,
  }));

  return (
    <div>
      <h3>{symbol} — {interval}</h3>
      <ResponsiveContainer width="100%" height={300}>
        <LineChart data={chartData}>
          <CartesianGrid strokeDasharray="3 3" />
          <XAxis dataKey="time" minTickGap={40} />
          <YAxis domain={["auto", "auto"]} />
          <Tooltip />
          <Line type="monotone" dataKey="close" stroke="#4f8cff" dot={false} strokeWidth={2} />
        </LineChart>
      </ResponsiveContainer>
    </div>
  );
}
