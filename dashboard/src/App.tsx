import { useEffect, useState } from "react";
import { fetchSymbols } from "./api";
import PriceChart from "./components/PriceChart";
import "./App.css";
import TopSymbols from "./components/TopSymbols";
import CorrelationHeatmap from "./components/CorrelationHeatmap";
import SimplicialComplex from "./components/SimplicialComplex";

export default function App() {
  const [symbols, setSymbols] = useState<string[]>([]);
  const [selected, setSelected] = useState<string>("");
  const [interval, setInterval_] = useState("1m");
  const [limit, setLimit] = useState(60);

  useEffect(() => {
    fetchSymbols().then((syms) => {
      setSymbols(syms);
      if (syms.length > 0) setSelected(syms[0]);
    });
  }, []);

  return (
    <div style={{ padding: "2rem", fontFamily: "system-ui" }}>
      <h1>PULSE</h1>

      <div style={{ marginBottom: "1rem" }}>
        <select value={selected} onChange={(e) => setSelected(e.target.value)}>
          {symbols.map((s) => (
            <option key={s} value={s}>{s}</option>
          ))}
        </select>

        <select value={interval} onChange={(e) => setInterval_(e.target.value)} style={{ marginLeft: "1rem" }}>
          <option value="1m">1m</option>
          <option value="5m">5m</option>
          <option value="15m">15m</option>
          <option value="1h">1h</option>
        </select>

        <select value={limit} onChange={(e) => setLimit(Number(e.target.value))} style={{ marginLeft: "1rem" }}>
          <option value={30}>Last 30 buckets</option>
          <option value={60}>Last 60 buckets</option>
          <option value={120}>Last 120 buckets</option>
        </select>
      </div>

      {selected && <PriceChart symbol={selected} interval={interval} limit={limit} />}

      <div style={{ display: "flex", gap: "2rem", marginTop: "2rem", flexWrap: "wrap" }}>
        <TopSymbols onSelectSymbol={setSelected} />
        <CorrelationHeatmap />
      </div>

      {selected && (
        <div style={{ marginTop: "2rem" }}>
          <SimplicialComplex symbol={selected} />
        </div>
      )}
    </div>
  );
}
