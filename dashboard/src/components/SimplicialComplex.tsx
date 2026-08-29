import { usePhaseSpace } from "../hooks/useWebSocket"; // rename file/hook if you like

interface TdaData {
  points: number[][];
  edges: number[][];
  betti_0: number;
  betti_1: number;
}

export default function SimplicialComplex({ symbol }: { symbol: string }) {
  const data = usePhaseSpace(symbol) as unknown as TdaData | null;
  if (!data) return <div>Connecting...</div>;

  const width = 400, height = 300, pad = 20;
  const xs = data.points.map((p) => p[0]);
  const ys = data.points.map((p) => p[1]);
  const xMin = Math.min(...xs), xMax = Math.max(...xs);
  const yMin = Math.min(...ys), yMax = Math.max(...ys);

  const scaleX = (x: number) => pad + ((x - xMin) / (xMax - xMin || 1)) * (width - 2 * pad);
  const scaleY = (y: number) => height - pad - ((y - yMin) / (yMax - yMin || 1)) * (height - 2 * pad);

  return (
    <div>
      <h3>{symbol} — 1-Skeleton (β₀={data.betti_0}, β₁={data.betti_1})</h3>
      <svg width={width} height={height} style={{ background: "#111", borderRadius: 4 }}>
        {data.edges.map(([i, j], idx) => (
          <line
            key={idx}
            x1={scaleX(data.points[i][0])} y1={scaleY(data.points[i][1])}
            x2={scaleX(data.points[j][0])} y2={scaleY(data.points[j][1])}
            stroke="#4f8cff" strokeWidth={0.5} opacity={0.5}
          />
        ))}
        {data.points.map((p, idx) => (
          <circle key={idx} cx={scaleX(p[0])} cy={scaleY(p[1])} r={3} fill="#ff8c4f" />
        ))}
      </svg>
      <p style={{ fontSize: "0.85em", color: "#888" }}>
        β₀ = connected components, β₁ = independent cycles in the trade point cloud (price delta vs. log volume)
      </p>
    </div>
  );
}
