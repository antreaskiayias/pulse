import { fetchCorrelation } from "../api";
import { usePolling } from "../hooks/usePolling";

function colorFor(value: number): string {
  // -1 -> red, 0 -> neutral gray, 1 -> blue
  if (value >= 0) {
    const intensity = Math.round(value * 200);
    return `rgb(${255 - intensity}, ${255 - intensity}, 255)`;
  }
  const intensity = Math.round(-value * 200);
  return `rgb(255, ${255 - intensity}, ${255 - intensity})`;
}

export default function CorrelationHeatmap() {
  const { data, error } = usePolling(() => fetchCorrelation("1m", 60), 15000, []);

  if (error) return <div className="error">Failed to load: {error}</div>;
  if (!data || data.symbols.length === 0) return <div>Loading...</div>;

  return (
    <div>
      <h3>Price Correlation (last 60m)</h3>
      <table style={{ borderCollapse: "collapse" }}>
        <thead>
          <tr>
            <th></th>
            {data.symbols.map((s) => (
              <th key={s} style={{ padding: "4px 8px", fontSize: "0.8em" }}>{s}</th>
            ))}
          </tr>
        </thead>
        <tbody>
          {data.symbols.map((s1, i) => (
            <tr key={s1}>
              <td style={{ fontSize: "0.8em", paddingRight: "8px" }}>{s1}</td>
              {data.symbols.map((s2, j) => (
                <td
                  key={s2}
                  style={{
                    background: colorFor(data.matrix[i][j]),
                    width: "50px",
                    height: "40px",
                    textAlign: "center",
                    fontSize: "0.75em",
                    border: "1px solid #eee",
                  }}
                >
                  {data.matrix[i][j].toFixed(2)}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
