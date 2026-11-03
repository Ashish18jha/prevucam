import { Bar, BarChart, CartesianGrid, Cell, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { Panel, Empty } from "./UI";

const AXIS = { stroke: "#4c5765", fontSize: 11, tickLine: false, axisLine: false };
const PALETTE = ["#22d3ee", "#f5a524", "#f0524f", "#34d399", "#a78bfa", "#60a5fa", "#f472b6", "#94a3b8"];

const tooltip = {
  contentStyle: { background: "#141b24", border: "1px solid #2a3542", borderRadius: 8, fontSize: 12 },
  labelStyle: { color: "#dbe3ec" },
  cursor: { fill: "rgba(255,255,255,0.04)" },
};

export function ChartCard({ title, data, horizontal = false, color, height = 220 }) {
  const total = (data || []).reduce((s, d) => s + d.count, 0);
  return (
    <Panel title={title} actions={<span className="muted mono">{total}</span>}>
      {!data?.length || total === 0 ? (
        <Empty title="No data yet">Events will appear here as they are recorded.</Empty>
      ) : (
        <ResponsiveContainer width="100%" height={height}>
          {horizontal ? (
            <BarChart data={data} layout="vertical" margin={{ left: 8, right: 16 }}>
              <CartesianGrid horizontal={false} stroke="#1e2732" />
              <XAxis type="number" allowDecimals={false} {...AXIS} />
              <YAxis type="category" dataKey="label" width={110} {...AXIS} />
              <Tooltip {...tooltip} />
              <Bar dataKey="count" radius={[0, 4, 4, 0]} barSize={16}>
                {data.map((_, i) => <Cell key={i} fill={color || PALETTE[i % PALETTE.length]} />)}
              </Bar>
            </BarChart>
          ) : (
            <BarChart data={data} margin={{ left: -18, right: 8 }}>
              <CartesianGrid vertical={false} stroke="#1e2732" />
              <XAxis dataKey="label" {...AXIS} interval="preserveStartEnd" minTickGap={14} />
              <YAxis allowDecimals={false} {...AXIS} />
              <Tooltip {...tooltip} />
              <Bar dataKey="count" fill={color || "#22d3ee"} radius={[4, 4, 0, 0]} />
            </BarChart>
          )}
        </ResponsiveContainer>
      )}
    </Panel>
  );
}
