import React, { useState, useMemo, useRef, useEffect } from "react";
import {
  ResponsiveContainer,
  LineChart,
  Line,
  BarChart,
  Bar,
  AreaChart,
  Area,
  ScatterChart,
  Scatter,
  ZAxis,
  PieChart,
  Pie,
  Cell,
  Treemap,
  FunnelChart,
  Funnel,
  LabelList,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  Legend,
} from "recharts";
import {
  TrendingUp,
  TrendingDown,
  Minus,
  Search,
  ChevronUp,
  ChevronDown,
  Copy,
  Check,
  Code2,
  BarChart2,
  List,
  Sparkles,
  X,
  AlertCircle,
} from "lucide-react";
import type { Artifact } from "../types";

// ---------------------------------------------------------------------------
// Palette
// ---------------------------------------------------------------------------
const P = [
  "#6366f1",
  "#06b6d4",
  "#10b981",
  "#f59e0b",
  "#ef4444",
  "#8b5cf6",
  "#ec4899",
  "#84cc16",
  "#f97316",
  "#14b8a6",
];

// ---------------------------------------------------------------------------
// Truncate + custom axis ticks (prevents label overlap)
// ---------------------------------------------------------------------------
const trunc = (s: unknown, n: number): string => {
  const str = String(s ?? "");
  return str.length <= n ? str : str.slice(0, n) + "…";
};

// eslint-disable-next-line @typescript-eslint/no-explicit-any
const XTick: React.FC<any> = ({ x, y, payload }) => {
  const raw = String(payload?.value ?? "");
  const label = trunc(raw, 11);
  return (
    <g transform={`translate(${x},${y})`}>
      {raw !== label && <title>{raw}</title>}
      <text
        x={0}
        y={0}
        dy={10}
        textAnchor="end"
        fill="#6b7280"
        fontSize={10}
        transform="rotate(-28)"
      >
        {label}
      </text>
    </g>
  );
};

// eslint-disable-next-line @typescript-eslint/no-explicit-any
const YTick: React.FC<any> = ({ x, y, payload }) => {
  const raw = String(payload?.value ?? "");
  const label = trunc(raw, 15);
  return (
    <g transform={`translate(${x},${y})`}>
      {raw !== label && <title>{raw}</title>}
      <text x={-6} y={0} dy={4} textAnchor="end" fill="#6b7280" fontSize={10}>
        {label}
      </text>
    </g>
  );
};

// eslint-disable-next-line @typescript-eslint/no-explicit-any
const NumTick: React.FC<any> = ({ x, y, payload }) => {
  const raw = String(payload?.value ?? "");
  const label = Number(payload?.value ?? 0).toLocaleString("en-US", {
    notation: "compact",
    maximumFractionDigits: 1,
  });
  return (
    <g transform={`translate(${x},${y})`}>
      <title>{raw}</title>
      <text x={0} y={0} dy={4} textAnchor="middle" fill="#6b7280" fontSize={10}>
        {label}
      </text>
    </g>
  );
};

// ---------------------------------------------------------------------------
// Config interfaces (mirrors BE contracts)
// ---------------------------------------------------------------------------
interface ChartEncoding {
  x?: string;
  y?: string;
  series?: string;
  size?: string;
  category?: string;
  value?: string;
}

interface ChartCfg {
  orientation?: "vertical" | "horizontal";
  show_legend?: boolean;
  show_data_labels?: boolean;
  show_grid?: boolean;
  sort_order?: "asc" | "desc" | "none";
  stack_type?: "value" | "percent";
  line_style?: "solid" | "dashed" | "dotted";
  fill_opacity?: number;
  x_axis_label?: string;
  y_axis_label?: string;
}

interface KPIDisplay {
  prefix?: string;
  suffix?: string;
  decimal_places?: number;
  trend_direction?: "up_is_good" | "down_is_good";
  comparison_label?: string;
  color_theme?: "default" | "positive" | "negative" | "warning";
}

interface TableCol {
  field: string;
  label: string;
  format?: "currency" | "number" | "percent" | "date" | null;
  align?: "left" | "center" | "right";
  sortable?: boolean;
  width_hint?: "xs" | "sm" | "md" | "lg" | "xl";
}

interface TableCfg {
  default_sort_column?: string | null;
  default_sort_direction?: "asc" | "desc";
  show_row_numbers?: boolean;
  enable_search?: boolean;
  page_size?: number | null;
}

// ---------------------------------------------------------------------------
// Recharts shared styles (dark theme)
// ---------------------------------------------------------------------------
const TT = {
  contentStyle: {
    background: "#111827",
    border: "1px solid rgba(255,255,255,0.1)",
    borderRadius: "8px",
    fontSize: "12px",
    color: "#e2e8f0",
    boxShadow: "0 8px 32px rgba(0,0,0,0.5)",
    padding: "8px 12px",
  },
  itemStyle: { color: "#e2e8f0" },
  labelStyle: { color: "#94a3b8", fontWeight: 600 },
  cursor: { fill: "rgba(255,255,255,0.04)" },
};

const AX = {
  tick: { fill: "#6b7280", fontSize: 10 },
  axisLine: { stroke: "rgba(255,255,255,0.07)" },
  tickLine: { stroke: "rgba(255,255,255,0.07)" },
};

const GRID = { stroke: "rgba(255,255,255,0.05)", strokeDasharray: "3 3" };

const WIDTH_HINT_PX: Record<string, number> = {
  xs: 60,
  sm: 100,
  md: 160,
  lg: 240,
  xl: 360,
};

// ---------------------------------------------------------------------------
// Formatting utilities
// ---------------------------------------------------------------------------
function fmtKpi(value: number, format: string, cfg: KPIDisplay = {}): string {
  const decimals =
    cfg.decimal_places ??
    (format === "currency" ? 2 : format === "percent" ? 2 : 0);

  if (format === "percent") return `${value.toFixed(decimals)}%`;

  const prefix = cfg.prefix ?? (format === "currency" ? "$" : "");
  const suffix = cfg.suffix ?? "";

  if (suffix === "B") return `${prefix}${(value / 1_000_000_000).toFixed(1)}B`;
  if (suffix === "M") return `${prefix}${(value / 1_000_000).toFixed(1)}M`;
  if (suffix === "K") return `${prefix}${(value / 1_000).toFixed(1)}K`;

  return `${prefix}${value.toLocaleString("en-US", { minimumFractionDigits: decimals, maximumFractionDigits: decimals })}${suffix}`;
}

function fmtCell(value: unknown, fmt?: string | null): string {
  if (value === null || value === undefined) return "—";
  const num = Number(value);
  if (fmt && !Number.isNaN(num)) {
    if (fmt === "currency")
      return `$${num.toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;
    if (fmt === "number") return num.toLocaleString("en-US");
    if (fmt === "percent") return `${num.toFixed(2)}%`;
    if (fmt === "date") return new Date(String(value)).toLocaleDateString();
  }
  return String(value);
}

// ---------------------------------------------------------------------------
// Data prep
// ---------------------------------------------------------------------------
function sortRows(
  data: Record<string, unknown>[],
  field: string,
  order: string,
) {
  if (order === "none" || !field) return data;
  return [...data].sort((a, b) => {
    const av = Number(a[field]) || 0;
    const bv = Number(b[field]) || 0;
    return order === "asc" ? av - bv : bv - av;
  });
}

function pivotSeries(
  data: Record<string, unknown>[],
  xF: string,
  yF: string,
  sF: string,
): { rows: Record<string, unknown>[]; keys: string[] } {
  const map = new Map<string, Record<string, unknown>>();
  const keys = new Set<string>();
  for (const row of data) {
    const xVal = String(row[xF] ?? "");
    const sv = String(row[sF] ?? "");
    keys.add(sv);
    if (!map.has(xVal)) map.set(xVal, { [xF]: xVal });
    const g = map.get(xVal)!;
    g[sv] = Number(row[yF]) || 0;
  }
  return { rows: Array.from(map.values()), keys: Array.from(keys) };
}

function prepWaterfall(
  data: Record<string, unknown>[],
  xF: string,
  yF: string,
) {
  let running = 0;
  return data.map((row) => {
    const val = Number(row[yF]) || 0;
    const base = val >= 0 ? running : running + val;
    const r = { [xF]: row[xF], base, bar: Math.abs(val), positive: val >= 0 };
    running += val;
    return r;
  });
}

// ---------------------------------------------------------------------------
// Mini KPI preview
// ---------------------------------------------------------------------------
const MiniKpi: React.FC<{ a: Artifact }> = ({ a }) => {
  const cfg = a.config || {};
  const cardType = cfg.card_type || "single_value";
  const format = cfg.format || "number";
  const disp: KPIDisplay = cfg.display_config || {};
  const kn = a.key_numbers || {};
  const THEME = {
    default: "#6366f1",
    positive: "#10b981",
    negative: "#ef4444",
    warning: "#f59e0b",
  };
  const accent = THEME[disp.color_theme as keyof typeof THEME] || THEME.default;
  const value = Number(kn.value ?? 0);
  const formatted = fmtKpi(value, format, disp);

  if (cardType === "value_with_delta") {
    const dp = Number(kn.delta_pct ?? 0);
    const good = disp.trend_direction === "down_is_good" ? dp < 0 : dp > 0;
    const dc = dp === 0 ? "#6b7280" : good ? "#10b981" : "#ef4444";
    return (
      <div className="artifact-mini-kpi">
        <div className="artifact-mini-kpi-value" style={{ color: accent }}>
          {formatted}
        </div>
        <div className="artifact-mini-kpi-delta" style={{ color: dc }}>
          {dp > 0 ? (
            <TrendingUp size={11} />
          ) : dp < 0 ? (
            <TrendingDown size={11} />
          ) : (
            <Minus size={11} />
          )}
          <span>
            {dp > 0 ? "+" : ""}
            {dp.toFixed(1)}%
          </span>
        </div>
      </div>
    );
  }

  if (cardType === "value_with_target") {
    const target = Number(kn.target ?? 0);
    const pct = target > 0 ? Math.min(100, (value / target) * 100) : 0;
    return (
      <div className="artifact-mini-kpi">
        <div className="artifact-mini-kpi-value" style={{ color: accent }}>
          {formatted}
        </div>
        <div className="artifact-mini-kpi-progress-bar">
          <div
            className="artifact-mini-kpi-progress-fill"
            style={{
              width: `${pct}%`,
              background: value >= target ? "#10b981" : "#f59e0b",
            }}
          />
        </div>
        <div style={{ fontSize: 10, color: "#6b7280" }}>
          {pct.toFixed(0)}% of target
        </div>
      </div>
    );
  }

  return (
    <div className="artifact-mini-kpi">
      <div className="artifact-mini-kpi-value" style={{ color: accent }}>
        {formatted}
      </div>
    </div>
  );
};

// ---------------------------------------------------------------------------
// Mini chart preview (no axes, no labels, no animation)
// ---------------------------------------------------------------------------
const MiniChart: React.FC<{ a: Artifact }> = ({ a }) => {
  const config = a.config || {};
  const ct = config.chart_type || "bar";
  const enc: ChartEncoding = config.encoding || {};
  const data = (a.result_data || []).slice(0, 12);

  const ccfgMini = config.chart_config || {};
  const isHMini = ccfgMini.orientation === "horizontal";
  const xF = enc.x || (data[0] ? Object.keys(data[0])[0] : "");
  const yF = enc.y || (data[0] ? Object.keys(data[0])[1] : "");
  const catF = enc.category || xF;
  const valF = enc.value || yF;

  if (!data.length) {
    return <div className="artifact-mini-empty">No data</div>;
  }

  const margin = { top: 2, right: 2, bottom: 2, left: 2 };

  // Part-to-whole
  if (ct === "donut" || ct === "treemap") {
    const pData = data.slice(0, 8).map((r) => ({
      name: String(r[catF] ?? ""),
      value: Number(r[valF] ?? 0),
    }));
    return (
      <ResponsiveContainer width="100%" height={68}>
        <PieChart margin={margin}>
          <Pie
            data={pData}
            dataKey="value"
            cx="50%"
            cy="50%"
            innerRadius={ct === "donut" ? "40%" : 0}
            outerRadius="85%"
            paddingAngle={1}
            isAnimationActive={false}
            label={false}
          >
            {pData.map((_, i) => (
              <Cell key={i} fill={P[i % P.length]} />
            ))}
          </Pie>
        </PieChart>
      </ResponsiveContainer>
    );
  }

  if (ct === "funnel") {
    const fData = data.slice(0, 5).map((r, i) => ({
      name: String(r[catF] ?? ""),
      value: Number(r[valF] ?? 0),
      fill: P[i % P.length],
    }));
    return (
      <ResponsiveContainer width="100%" height={68}>
        <FunnelChart margin={margin}>
          <Funnel dataKey="value" data={fData} isAnimationActive={false}>
            {fData.map((e, i) => (
              <Cell key={i} fill={e.fill} />
            ))}
          </Funnel>
        </FunnelChart>
      </ResponsiveContainer>
    );
  }

  if (ct === "scatter" || ct === "bubble") {
    const sd = data.map((r) => ({
      x: Number(r[xF]) || 0,
      y: Number(r[yF]) || 0,
    }));
    return (
      <ResponsiveContainer width="100%" height={68}>
        <ScatterChart margin={margin}>
          <Scatter
            data={sd}
            fill={P[0]}
            fillOpacity={0.7}
            isAnimationActive={false}
          />
        </ScatterChart>
      </ResponsiveContainer>
    );
  }

  if (ct === "area") {
    return (
      <ResponsiveContainer width="100%" height={68}>
        <AreaChart data={data} margin={margin}>
          <Area
            dataKey={yF}
            stroke={P[0]}
            fill={P[0]}
            fillOpacity={0.25}
            strokeWidth={1.5}
            dot={false}
            isAnimationActive={false}
          />
        </AreaChart>
      </ResponsiveContainer>
    );
  }

  if (ct === "line" || ct === "box_plot") {
    return (
      <ResponsiveContainer width="100%" height={68}>
        <LineChart data={data} margin={margin}>
          <Line
            dataKey={yF}
            stroke={P[0]}
            strokeWidth={1.5}
            dot={false}
            isAnimationActive={false}
          />
        </LineChart>
      </ResponsiveContainer>
    );
  }

  // Default: bar
  return (
    <ResponsiveContainer width="100%" height={68}>
      <BarChart data={data} margin={margin} barCategoryGap="25%" layout={isHMini ? "vertical" : "horizontal"}>
        <Bar
          dataKey={isHMini ? xF : yF}
          fill={P[0]}
          isAnimationActive={false}
          radius={isHMini ? [0, 1, 1, 0] : [1, 1, 0, 0]}
        />
      </BarChart>
    </ResponsiveContainer>
  );
};

// ---------------------------------------------------------------------------
// Mini table preview
// ---------------------------------------------------------------------------
const MiniTable: React.FC<{ a: Artifact }> = ({ a }) => {
  const cols: TableCol[] = a.config?.columns || [];
  const data = (a.result_data || []).slice(0, 4);
  const headers =
    cols.length > 0
      ? cols.slice(0, 3).map((c) => ({ field: c.field, label: c.label }))
      : data[0]
        ? Object.keys(data[0])
            .slice(0, 3)
            .map((k) => ({ field: k, label: k }))
        : [];

  if (!data.length || !headers.length) {
    return <div className="artifact-mini-empty">No data</div>;
  }

  return (
    <div style={{ width: "100%", overflowX: "hidden" }}>
      <table className="artifact-mini-table">
        <thead>
          <tr>
            {headers.map((h) => (
              <th
                key={h.field}
                style={{
                  maxWidth: 56,
                  overflow: "hidden",
                  textOverflow: "ellipsis",
                  whiteSpace: "nowrap",
                }}
              >
                {h.label.slice(0, 8)}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {data.map((row, i) => (
            <tr key={i}>
              {headers.map((h) => (
                <td
                  key={h.field}
                  style={{
                    maxWidth: 56,
                    overflow: "hidden",
                    textOverflow: "ellipsis",
                    whiteSpace: "nowrap",
                  }}
                >
                  {String(row[h.field] ?? "").slice(0, 10)}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
};

// ---------------------------------------------------------------------------
// Full KPI renderer
// ---------------------------------------------------------------------------
const FullKpi: React.FC<{ a: Artifact }> = ({ a }) => {
  const cfg = a.config || {};
  const cardType = cfg.card_type || "single_value";
  const format = cfg.format || "number";
  const disp: KPIDisplay = cfg.display_config || {};
  const kn = a.key_numbers || {};
  const THEME = {
    default: "#6366f1",
    positive: "#10b981",
    negative: "#ef4444",
    warning: "#f59e0b",
  };
  const accent = THEME[disp.color_theme as keyof typeof THEME] || THEME.default;
  const value = Number(kn.value ?? 0);
  const formatted = fmtKpi(value, format, disp);

  return (
    <div
      className="kpi-card-full"
      style={{ "--kpi-accent": accent } as React.CSSProperties}
    >
      <div className="kpi-card-title">{a.title}</div>
      <div className="kpi-card-value">{formatted}</div>

      {cardType === "value_with_delta" &&
        (() => {
          const dp = Number(kn.delta_pct ?? 0);
          const da = kn.delta_abs != null ? Number(kn.delta_abs) : null;
          const good =
            disp.trend_direction === "down_is_good" ? dp < 0 : dp > 0;
          const dc = dp === 0 ? "#6b7280" : good ? "#10b981" : "#ef4444";
          return (
            <div className="kpi-delta-row">
              <span
                className="kpi-delta-badge"
                style={{ background: `${dc}22`, color: dc }}
              >
                {dp > 0 ? (
                  <TrendingUp size={13} />
                ) : dp < 0 ? (
                  <TrendingDown size={13} />
                ) : (
                  <Minus size={13} />
                )}
                <span>
                  {dp > 0 ? "+" : ""}
                  {dp.toFixed(1)}%
                </span>
              </span>
              {da !== null && (
                <span className="kpi-delta-abs">
                  ({da > 0 ? "+" : ""}
                  {fmtKpi(da, format, disp)})
                </span>
              )}
              {disp.comparison_label && (
                <span className="kpi-comparison-label">
                  {disp.comparison_label}
                </span>
              )}
            </div>
          );
        })()}

      {cardType === "value_with_target" &&
        (() => {
          const target = Number(kn.target ?? 0);
          const dp = kn.delta_pct != null ? Number(kn.delta_pct) : null;
          const pct = target > 0 ? Math.min(100, (value / target) * 100) : 0;
          const onTarget = value >= target;
          return (
            <div className="kpi-target-section">
              <div className="kpi-target-labels">
                <span>
                  Actual:{" "}
                  <strong style={{ color: "#e2e8f0" }}>{formatted}</strong>
                </span>
                <span>
                  Target:{" "}
                  <strong style={{ color: "#e2e8f0" }}>
                    {fmtKpi(target, format, disp)}
                  </strong>
                </span>
              </div>
              <div className="kpi-progress-bar">
                <div
                  className="kpi-progress-fill"
                  style={{
                    width: `${pct}%`,
                    background: onTarget ? "#10b981" : "#f59e0b",
                  }}
                />
              </div>
              <div className="kpi-target-meta">
                {onTarget ? (
                  <span style={{ color: "#10b981" }}>✓ Target achieved</span>
                ) : (
                  <span style={{ color: "#f59e0b" }}>
                    {pct.toFixed(0)}% of target
                  </span>
                )}
                {dp !== null && (
                  <span style={{ color: dp >= 0 ? "#10b981" : "#ef4444" }}>
                    {dp >= 0 ? "+" : ""}
                    {dp.toFixed(1)}%
                  </span>
                )}
              </div>
            </div>
          );
        })()}

      {a.note && <div className="kpi-card-note">{a.note}</div>}
    </div>
  );
};

// ---------------------------------------------------------------------------
// Full chart renderer (Recharts)
// ---------------------------------------------------------------------------
const FullChart: React.FC<{ a: Artifact }> = ({ a }) => {
  const cfg = a.config || {};
  const ct: string = cfg.chart_type || "bar";
  const enc: ChartEncoding = cfg.encoding || {};
  const ccfg: ChartCfg = cfg.chart_config || {};
  const data = a.result_data || [];

  const xF = enc.x || (data[0] ? Object.keys(data[0])[0] : "");
  const yF = enc.y || (data[0] ? Object.keys(data[0])[1] : "");
  const sF = enc.series;
  const catF = enc.category || xF;
  const valF = enc.value || yF;
  const szF = enc.size;

  const isH = ccfg.orientation === "horizontal";
  const showLeg = ccfg.show_legend !== false && data.length > 0;
  const showGrid = ccfg.show_grid !== false;
  const showLabels = ccfg.show_data_labels === true;
  const sortedData = useMemo(
    () => sortRows(data, isH ? xF : yF, ccfg.sort_order || "none"),
    [data, isH, xF, yF, ccfg.sort_order],
  );
  const lineDash =
    ccfg.line_style === "dashed"
      ? "5 5"
      : ccfg.line_style === "dotted"
        ? "2 4"
        : undefined;
  const fillOp = ccfg.fill_opacity ?? 0.2;
  const margin = {
    top: 10,
    right: 24,
    bottom: isH ? 10 : 56,
    left: isH ? 8 : 10,
  };

  const xAxisProps = isH
    ? {
        type: "number" as const,
        tick: <NumTick />,
        axisLine: AX.axisLine,
        tickLine: AX.tickLine,
      }
    : {
        dataKey: xF,
        tick: <XTick />,
        axisLine: AX.axisLine,
        tickLine: AX.tickLine,
        height: 68,
        interval: 0 as const,
      };
  const yAxisProps = isH
    ? {
        dataKey: yF,
        type: "category" as const,
        tick: <YTick />,
        axisLine: AX.axisLine,
        tickLine: AX.tickLine,
        width: 96,
      }
    : { tick: <NumTick />, axisLine: AX.axisLine, tickLine: AX.tickLine };

  // --- Funnel ---
  if (ct === "funnel") {
    const fd = sortedData.map((r, i) => ({
      name: String(r[catF] ?? ""),
      value: Number(r[valF] ?? 0),
      fill: P[i % P.length],
    }));
    return (
      <ResponsiveContainer width="100%" height={320}>
        <FunnelChart>
          <Tooltip {...TT} />
          <Funnel
            dataKey="value"
            data={fd}
            isAnimationActive
            animationDuration={700}
          >
            {showLabels && (
              <LabelList
                position="right"
                fill="#9ca3af"
                fontSize={10}
                dataKey="name"
                formatter={(v: unknown) => trunc(String(v ?? ""), 14)}
              />
            )}
            {fd.map((e, i) => (
              <Cell key={i} fill={e.fill} />
            ))}
          </Funnel>
        </FunnelChart>
      </ResponsiveContainer>
    );
  }

  // --- Donut / Pie / Treemap ---
  if (ct === "donut" || ct === "pie" || ct === "treemap") {
    if (ct === "treemap") {
      const td = sortedData.map((r) => ({
        name: String(r[catF] ?? ""),
        size: Number(r[valF] ?? 0),
      }));
      return (
        <ResponsiveContainer width="100%" height={320}>
          <Treemap
            data={td}
            dataKey="size"
            aspectRatio={4 / 3}
            stroke="rgba(0,0,0,0.3)"
            isAnimationActive
            animationDuration={700}
            // eslint-disable-next-line @typescript-eslint/no-explicit-any
            content={
              ((props: any) => {
                const { x, y, width, height, index, name } = props as {
                  x: number;
                  y: number;
                  width: number;
                  height: number;
                  index: number;
                  name: string;
                };
                if (!width || !height) return null;
                return (
                  <g>
                    <rect
                      x={x}
                      y={y}
                      width={width}
                      height={height}
                      fill={P[index % P.length]}
                      fillOpacity={0.85}
                      stroke="rgba(0,0,0,0.3)"
                      strokeWidth={1}
                      rx={2}
                    />
                    {width > 50 && height > 28 && (
                      <text
                        x={x + width / 2}
                        y={y + height / 2}
                        textAnchor="middle"
                        dominantBaseline="middle"
                        fontSize={Math.min(12, Math.floor(width / 7))}
                        fill="#fff"
                        fontWeight={600}
                      >
                        {trunc(String(name), 14)}
                      </text>
                    )}
                  </g>
                );
              }) as unknown as React.ReactElement
            }
          />
        </ResponsiveContainer>
      );
    }

    const pd = sortedData.map((r) => ({
      name: String(r[catF] ?? ""),
      value: Number(r[valF] ?? 0),
    }));
    return (
      <ResponsiveContainer width="100%" height={320}>
        <PieChart>
          <Pie
            data={pd}
            dataKey="value"
            nameKey="name"
            cx="50%"
            cy="50%"
            innerRadius={ct === "donut" ? "46%" : 0}
            outerRadius="68%"
            paddingAngle={ct === "donut" ? 3 : 1}
            isAnimationActive
            animationDuration={700}
            label={false}
          >
            {pd.map((_, i) => (
              <Cell key={i} fill={P[i % P.length]} />
            ))}
          </Pie>
          <Tooltip {...TT} />
          {showLeg && (
            <Legend
              wrapperStyle={{ fontSize: 11, color: "#9ca3af" }}
              formatter={(v) => trunc(String(v), 18)}
            />
          )}
        </PieChart>
      </ResponsiveContainer>
    );
  }

  // --- Waterfall ---
  if (ct === "waterfall") {
    const wd = prepWaterfall(sortedData, xF, yF);
    return (
      <ResponsiveContainer width="100%" height={320}>
        <BarChart data={wd} margin={margin}>
          {showGrid && <CartesianGrid {...GRID} />}
          <XAxis {...xAxisProps} />
          <YAxis {...yAxisProps} />
          <Tooltip
            {...TT}
            formatter={(v, n) =>
              n === "base" ? ["", ""] : [String(v), "Change"]
            }
          />
          {showLeg && (
            <Legend wrapperStyle={{ fontSize: 11, color: "#9ca3af" }} />
          )}
          <Bar
            dataKey="base"
            stackId="wf"
            fill="transparent"
            legendType="none"
          />
          <Bar
            dataKey="bar"
            stackId="wf"
            isAnimationActive
            animationDuration={700}
            radius={[3, 3, 0, 0]}
          >
            {wd.map((e: Record<string, unknown>, i: number) => (
              <Cell key={i} fill={e.positive ? "#10b981" : "#ef4444"} />
            ))}
          </Bar>
        </BarChart>
      </ResponsiveContainer>
    );
  }

  // --- Scatter / Bubble ---
  if (ct === "scatter" || ct === "bubble") {
    const sd = sortedData.map((r) => ({
      x: Number(r[xF]) || 0,
      y: Number(r[yF]) || 0,
      z: szF ? Number(r[szF]) || 1 : 10,
    }));
    return (
      <ResponsiveContainer width="100%" height={320}>
        <ScatterChart margin={{ top: 10, right: 24, bottom: 24, left: 10 }}>
          {showGrid && <CartesianGrid {...GRID} />}
          <XAxis
            dataKey="x"
            type="number"
            name={xF}
            tick={<NumTick />}
            axisLine={AX.axisLine}
            tickLine={AX.tickLine}
            label={
              ccfg.x_axis_label
                ? {
                    value: trunc(ccfg.x_axis_label, 18),
                    position: "insideBottom",
                    offset: -14,
                    fill: "#6b7280",
                    fontSize: 11,
                  }
                : undefined
            }
          />
          <YAxis
            dataKey="y"
            type="number"
            name={yF}
            tick={<NumTick />}
            axisLine={AX.axisLine}
            tickLine={AX.tickLine}
            label={
              ccfg.y_axis_label
                ? {
                    value: trunc(ccfg.y_axis_label, 18),
                    angle: -90,
                    position: "insideLeft",
                    fill: "#6b7280",
                    fontSize: 11,
                  }
                : undefined
            }
          />
          {ct === "bubble" && (
            <ZAxis dataKey="z" range={[40, 400]} name={szF} />
          )}
          <Tooltip
            {...TT}
            cursor={{
              strokeDasharray: "3 3",
              stroke: "rgba(255,255,255,0.15)",
            }}
          />
          <Scatter
            data={sd}
            fill={P[0]}
            fillOpacity={0.7}
            isAnimationActive
            animationDuration={700}
          />
        </ScatterChart>
      </ResponsiveContainer>
    );
  }

  // --- Heatmap (custom SVG grid) ---
  if (ct === "heatmap") {
    return (
      <HeatmapChart
        data={sortedData}
        xF={xF}
        yF={yF}
        valF={enc.value || ""}
      />
    );
  }

  // --- Grouped / Stacked bar with series ---
  if (ct === "grouped_bar" || ct === "stacked_bar") {
    const stackId = ct === "stacked_bar" ? "s" : undefined;
    const stackTypePct = ccfg.stack_type === "percent";

    // Detect if series field actually exists in data (long format) or if data is wide format
    const seriesInData = Boolean(sF && data.length > 0 && sF in data[0]);

    if (sF && seriesInData) {
      // Long format: pivot by series field
      const { rows, keys } = pivotSeries(sortedData, isH ? yF : xF, isH ? xF : yF, sF);
      return (
        <ResponsiveContainer width="100%" height={320}>
          <BarChart
            data={rows}
            margin={margin}
            layout={isH ? "vertical" : "horizontal"}
            stackOffset={stackTypePct ? "expand" : undefined}
          >
            {showGrid && <CartesianGrid {...GRID} />}
            <XAxis {...xAxisProps} />
            <YAxis
              {...yAxisProps}
              tickFormatter={!isH && stackTypePct ? (v) => `${(v * 100).toFixed(0)}%` : undefined}
            />
            <Tooltip
              {...TT}
              formatter={stackTypePct ? (v: unknown) => `${(Number(v) * 100).toFixed(1)}%` : undefined}
            />
            {showLeg && (
              <Legend wrapperStyle={{ fontSize: 11, color: "#9ca3af" }} formatter={(v) => trunc(String(v), 18)} />
            )}
            {keys.map((sv, i) => (
              <Bar key={sv} dataKey={sv} stackId={stackId} fill={P[i % P.length]}
                radius={stackId ? undefined : [2, 2, 0, 0]} isAnimationActive animationDuration={600 + i * 100}>
                {showLabels && (
                  <LabelList dataKey={sv} position={isH ? "right" : "top"}
                    style={{ fontSize: 10, fill: "#9ca3af" }}
                    formatter={(v: unknown) => trunc(String(v ?? ""), 8)} />
                )}
              </Bar>
            ))}
          </BarChart>
        </ResponsiveContainer>
      );
    } else {
      // Wide format: each numeric column except the category column is its own series
      const catKey = xF; // x encoding always holds the category field
      const wideKeys = data.length > 0
        ? Object.keys(data[0]).filter((k) => k !== catKey && typeof data[0][k] === "number")
        : yF ? [yF] : [];

      // For horizontal wide: Y axis shows categories (xF), X axis shows values
      const wideYAxisProps = isH
        ? { dataKey: catKey, type: "category" as const, tick: <YTick />, axisLine: AX.axisLine, tickLine: AX.tickLine, width: 140 }
        : { tick: <NumTick />, axisLine: AX.axisLine, tickLine: AX.tickLine };
      const wideXAxisProps = isH
        ? { type: "number" as const, tick: <NumTick />, axisLine: AX.axisLine, tickLine: AX.tickLine }
        : { dataKey: catKey, tick: <XTick />, axisLine: AX.axisLine, tickLine: AX.tickLine, height: 68, interval: 0 as const };

      const wideSorted = wideKeys.length > 0
        ? sortRows(data, wideKeys[0], ccfg.sort_order || "none")
        : data;

      const dynHeight = isH ? Math.max(320, wideSorted.length * 36 + 60) : 320;

      return (
        <ResponsiveContainer width="100%" height={dynHeight}>
          <BarChart
            data={wideSorted}
            margin={margin}
            layout={isH ? "vertical" : "horizontal"}
            stackOffset={stackTypePct ? "expand" : undefined}
          >
            {showGrid && <CartesianGrid {...GRID} />}
            <XAxis {...wideXAxisProps} />
            <YAxis
              {...wideYAxisProps}
              tickFormatter={!isH && stackTypePct ? (v) => `${(v * 100).toFixed(0)}%` : undefined}
            />
            <Tooltip
              {...TT}
              formatter={stackTypePct ? (v: unknown) => `${(Number(v) * 100).toFixed(1)}%` : undefined}
            />
            {showLeg && (
              <Legend wrapperStyle={{ fontSize: 11, color: "#9ca3af" }} formatter={(v) => trunc(String(v), 18)} />
            )}
            {wideKeys.map((k, i) => (
              <Bar key={k} dataKey={k} stackId={stackId} fill={P[i % P.length]}
                radius={stackId ? undefined : isH ? [0, 3, 3, 0] : [2, 2, 0, 0]}
                isAnimationActive animationDuration={600 + i * 100}>
                {showLabels && (
                  <LabelList dataKey={k} position={isH ? "right" : "top"}
                    style={{ fontSize: 10, fill: "#9ca3af" }}
                    formatter={(v: unknown) => trunc(String(v ?? ""), 8)} />
                )}
              </Bar>
            ))}
          </BarChart>
        </ResponsiveContainer>
      );
    }
  }

  // --- Area ---
  if (ct === "area") {
    const areaLines = sF
      ? (() => {
          const { rows, keys } = pivotSeries(sortedData, isH ? yF : xF, isH ? xF : yF, sF);
          return { rows, keys };
        })()
      : null;
    if (areaLines) {
      return (
        <ResponsiveContainer width="100%" height={320}>
          <AreaChart data={areaLines.rows} margin={margin}>
            {showGrid && <CartesianGrid {...GRID} />}
            <XAxis {...xAxisProps} />
            <YAxis {...yAxisProps} />
            <Tooltip {...TT} />
            {showLeg && (
              <Legend
                wrapperStyle={{ fontSize: 11, color: "#9ca3af" }}
                formatter={(v) => trunc(String(v), 18)}
              />
            )}
            {areaLines.keys.map((sv, i) => (
              <Area
                key={sv}
                dataKey={sv}
                stroke={P[i % P.length]}
                fill={P[i % P.length]}
                fillOpacity={fillOp}
                strokeWidth={1.5}
                strokeDasharray={lineDash}
                isAnimationActive
                animationDuration={600 + i * 100}
              />
            ))}
          </AreaChart>
        </ResponsiveContainer>
      );
    }
    return (
      <ResponsiveContainer width="100%" height={320}>
        <AreaChart data={sortedData} margin={margin}>
          {showGrid && <CartesianGrid {...GRID} />}
          <XAxis {...xAxisProps} />
          <YAxis {...yAxisProps} />
          <Tooltip {...TT} />
          {showLeg && (
            <Legend wrapperStyle={{ fontSize: 11, color: "#9ca3af" }} />
          )}
          <Area
            dataKey={yF}
            stroke={P[0]}
            fill={P[0]}
            fillOpacity={fillOp}
            strokeDasharray={lineDash}
            isAnimationActive
            animationDuration={700}
          />
        </AreaChart>
      </ResponsiveContainer>
    );
  }

  // --- Line / Box plot (with optional series) ---
  if (ct === "line" || ct === "box_plot") {
    const lines = sF
      ? (() => {
          const { rows, keys } = pivotSeries(sortedData, isH ? yF : xF, isH ? xF : yF, sF);
          return { rows, keys };
        })()
      : null;
    if (lines) {
      return (
        <ResponsiveContainer width="100%" height={320}>
          <LineChart data={lines.rows} margin={margin}>
            {showGrid && <CartesianGrid {...GRID} />}
            <XAxis {...xAxisProps} />
            <YAxis {...yAxisProps} />
            <Tooltip {...TT} />
            {showLeg && (
              <Legend
                wrapperStyle={{ fontSize: 11, color: "#9ca3af" }}
                formatter={(v) => trunc(String(v), 18)}
              />
            )}
            {lines.keys.map((sv, i) => (
              <Line
                key={sv}
                dataKey={sv}
                stroke={P[i % P.length]}
                strokeWidth={2}
                strokeDasharray={lineDash}
                dot={{ r: 2 }}
                activeDot={{ r: 5 }}
                isAnimationActive
                animationDuration={600 + i * 100}
              />
            ))}
          </LineChart>
        </ResponsiveContainer>
      );
    }
    return (
      <ResponsiveContainer width="100%" height={320}>
        <LineChart data={sortedData} margin={margin}>
          {showGrid && <CartesianGrid {...GRID} />}
          <XAxis {...xAxisProps} />
          <YAxis {...yAxisProps} />
          <Tooltip {...TT} />
          {showLeg && (
            <Legend wrapperStyle={{ fontSize: 11, color: "#9ca3af" }} />
          )}
          <Line
            dataKey={yF}
            stroke={P[0]}
            strokeWidth={2}
            strokeDasharray={lineDash}
            dot={{ r: 2, fill: P[0] }}
            activeDot={{ r: 5 }}
            isAnimationActive
            animationDuration={700}
          />
        </LineChart>
      </ResponsiveContainer>
    );
  }

  // --- Default: Bar / Grouped bar / Histogram ---
  const barDataKey = isH ? xF : yF;
  const seriesKeys = sF ? [...new Set(data.map((r) => String(r[sF] ?? "")))] : [];
  return (
    <ResponsiveContainer width="100%" height={320}>
      <BarChart
        data={sortedData}
        margin={margin}
        layout={isH ? "vertical" : "horizontal"}
      >
        {showGrid && <CartesianGrid {...GRID} />}
        <XAxis {...xAxisProps} />
        <YAxis {...yAxisProps} />
        <Tooltip {...TT} />
        {showLeg && sF ? (
          <Legend
            payload={seriesKeys.map((k, i) => ({
              value: k,
              type: "rect" as const,
              color: P[i % P.length],
            }))}
            wrapperStyle={{ fontSize: 11, color: "#9ca3af" }}
            formatter={(v) => trunc(String(v), 18)}
          />
        ) : showLeg ? (
          <Legend wrapperStyle={{ fontSize: 11, color: "#9ca3af" }} />
        ) : null}
        <Bar
          dataKey={barDataKey}
          fill={P[0]}
          radius={isH ? [0, 3, 3, 0] : [3, 3, 0, 0]}
          isAnimationActive
          animationDuration={700}
        >
          {sF
            ? sortedData.map((row, i) => {
                const sv = String(row[sF] ?? "");
                const idx = seriesKeys.indexOf(sv);
                return <Cell key={i} fill={P[idx < 0 ? 0 : idx % P.length]} />;
              })
            : null}
          {showLabels && (
            <LabelList
              dataKey={barDataKey}
              position={isH ? "right" : "top"}
              style={{ fontSize: 10, fill: "#9ca3af" }}
              formatter={(v: unknown) => trunc(String(v ?? ""), 10)}
            />
          )}
        </Bar>
      </BarChart>
    </ResponsiveContainer>
  );
};

// ---------------------------------------------------------------------------
// Heatmap (custom SVG since Recharts has no native heatmap)
// ---------------------------------------------------------------------------
const HeatmapChart: React.FC<{
  data: Record<string, unknown>[];
  xF: string;
  yF: string;
  valF: string;
}> = ({ data, xF, yF, valF }) => {
  const xs = useMemo(
    () => Array.from(new Set(data.map((r) => String(r[xF] ?? "")))),
    [data, xF],
  );
  const ys = useMemo(
    () => Array.from(new Set(data.map((r) => String(r[yF] ?? "")))),
    [data, yF],
  );
  const vals = useMemo(
    () => data.map((r) => Number(r[valF] ?? 0)),
    [data, valF],
  );
  const min = Math.min(...vals);
  const max = Math.max(...vals, 1);
  const map = useMemo(() => {
    const m = new Map<string, number>();
    data.forEach((r) => m.set(`${r[xF]}__${r[yF]}`, Number(r[valF] ?? 0)));
    return m;
  }, [data, xF, yF, valF]);

  const cellW = Math.max(24, Math.min(60, Math.floor(460 / xs.length)));
  const cellH = Math.max(18, Math.min(40, Math.floor(240 / ys.length)));
  const labelW = 80;
  const svgW = labelW + xs.length * cellW;
  const svgH = 24 + ys.length * cellH;

  const colorIntensity = (v: number) => {
    const t = max > min ? (v - min) / (max - min) : 0;
    const r = Math.round(99 + t * (239 - 99));
    const g = Math.round(102 + t * (68 - 102));
    const b = Math.round(241 + t * (68 - 241));
    return `rgb(${r},${g},${b})`;
  };

  return (
    <div style={{ overflowX: "auto", padding: "8px 16px" }}>
      <svg width={svgW} height={svgH} style={{ display: "block" }}>
        {xs.map((x, xi) => (
          <text
            key={x}
            x={labelW + xi * cellW + cellW / 2}
            y={14}
            textAnchor="middle"
            fontSize={9}
            fill="#6b7280"
          >
            {trunc(String(x), 7)}
          </text>
        ))}
        {ys.map((y, yi) => (
          <React.Fragment key={y}>
            <text
              x={labelW - 4}
              y={24 + yi * cellH + cellH / 2 + 4}
              textAnchor="end"
              fontSize={9}
              fill="#6b7280"
            >
              {trunc(String(y), 10)}
            </text>
            {xs.map((x, xi) => {
              const v = map.get(`${x}__${y}`) ?? 0;
              return (
                <g key={x}>
                  <rect
                    x={labelW + xi * cellW + 1}
                    y={24 + yi * cellH + 1}
                    width={cellW - 2}
                    height={cellH - 2}
                    rx={2}
                    fill={colorIntensity(v)}
                    fillOpacity={0.85}
                  />
                  {cellW > 32 && cellH > 20 && (
                    <text
                      x={labelW + xi * cellW + cellW / 2}
                      y={24 + yi * cellH + cellH / 2 + 4}
                      textAnchor="middle"
                      fontSize={8}
                      fill="#fff"
                      fontWeight={600}
                    >
                      {v.toLocaleString()}
                    </text>
                  )}
                </g>
              );
            })}
          </React.Fragment>
        ))}
      </svg>
    </div>
  );
};

// ---------------------------------------------------------------------------
// Full table renderer (sortable, searchable, paginated)
// ---------------------------------------------------------------------------
const FullTable: React.FC<{ a: Artifact }> = ({ a }) => {
  const tcols: TableCol[] = a.config?.columns || [];
  const tblCfg: TableCfg = a.config?.table_config || {};
  const data = a.result_data || [];

  const cols: TableCol[] =
    tcols.length > 0
      ? tcols
      : data[0]
        ? Object.keys(data[0]).map((k) => ({
            field: k,
            label: k,
            sortable: true,
          }))
        : [];

  const defSortCol = tblCfg.default_sort_column ?? cols[0]?.field ?? null;
  const defSortDir = tblCfg.default_sort_direction ?? "desc";
  const pageSize = tblCfg.page_size ?? (data.length > 50 ? 25 : null);
  const showRowNums = tblCfg.show_row_numbers ?? false;
  const enableSearch = tblCfg.enable_search ?? false;

  const [sortCol, setSortCol] = useState<string | null>(defSortCol);
  const [sortDir, setSortDir] = useState<"asc" | "desc">(defSortDir);
  const [search, setSearch] = useState("");
  const [page, setPage] = useState(1);

  const filtered = useMemo(() => {
    if (!search.trim()) return data;
    const q = search.toLowerCase();
    return data.filter((row) =>
      cols.some((c) =>
        String(row[c.field] ?? "")
          .toLowerCase()
          .includes(q),
      ),
    );
  }, [data, search, cols]);

  const sorted = useMemo(() => {
    if (!sortCol) return filtered;
    return [...filtered].sort((a, b) => {
      const av = a[sortCol];
      const bv = b[sortCol];
      const an = Number(av);
      const bn = Number(bv);
      if (!Number.isNaN(an) && !Number.isNaN(bn))
        return sortDir === "asc" ? an - bn : bn - an;
      return sortDir === "asc"
        ? String(av ?? "").localeCompare(String(bv ?? ""))
        : String(bv ?? "").localeCompare(String(av ?? ""));
    });
  }, [filtered, sortCol, sortDir]);

  const totalPages = pageSize ? Math.ceil(sorted.length / pageSize) : 1;
  const paginated = pageSize
    ? sorted.slice((page - 1) * pageSize, page * pageSize)
    : sorted;

  const handleSort = (field: string) => {
    if (sortCol === field) setSortDir((d) => (d === "asc" ? "desc" : "asc"));
    else {
      setSortCol(field);
      setSortDir("asc");
    }
    setPage(1);
  };

  const autoAlign = (c: TableCol): string => {
    if (c.align) return c.align;
    if (
      c.format === "currency" ||
      c.format === "number" ||
      c.format === "percent"
    )
      return "right";
    if (c.format === "date") return "center";
    return "left";
  };

  return (
    <div className="table-renderer">
      {(enableSearch || data.length > 10) && (
        <div className="table-renderer-toolbar">
          {enableSearch && (
            <div className="table-renderer-search">
              <Search size={12} style={{ color: "#6b7280", flexShrink: 0 }} />
              <input
                placeholder="Search…"
                value={search}
                onChange={(e) => {
                  setSearch(e.target.value);
                  setPage(1);
                }}
              />
            </div>
          )}
          <span className="table-renderer-count">
            {sorted.length.toLocaleString()} rows
          </span>
        </div>
      )}
      <div className="table-renderer-scroll">
        <table className="analytics-table">
          <thead>
            <tr>
              {showRowNums && (
                <th
                  style={{
                    width: 36,
                    textAlign: "center",
                    color: "#4b5563",
                    fontSize: 10,
                  }}
                >
                  #
                </th>
              )}
              {cols.map((c) => (
                <th
                  key={c.field}
                  style={{
                    textAlign: autoAlign(c) as React.CSSProperties["textAlign"],
                    cursor: c.sortable !== false ? "pointer" : "default",
                    userSelect: "none",
                    width: c.width_hint
                      ? WIDTH_HINT_PX[c.width_hint]
                      : undefined,
                    whiteSpace: "nowrap",
                  }}
                  onClick={() => c.sortable !== false && handleSort(c.field)}
                >
                  <span
                    style={{
                      display: "inline-flex",
                      alignItems: "center",
                      gap: 3,
                    }}
                  >
                    {c.label}
                    {sortCol === c.field &&
                      (sortDir === "asc" ? (
                        <ChevronUp size={10} style={{ color: "#6366f1" }} />
                      ) : (
                        <ChevronDown size={10} style={{ color: "#6366f1" }} />
                      ))}
                    {sortCol !== c.field && c.sortable !== false && (
                      <span style={{ opacity: 0.25 }}>
                        <ChevronDown size={9} />
                      </span>
                    )}
                  </span>
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {paginated.map((row, i) => (
              <tr key={i}>
                {showRowNums && (
                  <td
                    style={{
                      textAlign: "center",
                      color: "#4b5563",
                      fontSize: 10,
                    }}
                  >
                    {(page - 1) * (pageSize || 0) + i + 1}
                  </td>
                )}
                {cols.map((c) => (
                  <td
                    key={c.field}
                    style={{
                      textAlign: autoAlign(
                        c,
                      ) as React.CSSProperties["textAlign"],
                    }}
                  >
                    {fmtCell(row[c.field], c.format)}
                  </td>
                ))}
              </tr>
            ))}
            {paginated.length === 0 && (
              <tr>
                <td
                  colSpan={cols.length + (showRowNums ? 1 : 0)}
                  style={{
                    textAlign: "center",
                    color: "#4b5563",
                    padding: "24px",
                  }}
                >
                  No results
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </div>
      {pageSize && totalPages > 1 && (
        <div className="table-renderer-pagination">
          <span>
            Page {page} of {totalPages}
          </span>
          <button
            type="button"
            onClick={() => setPage((p) => Math.max(1, p - 1))}
            disabled={page === 1}
          >
            <ChevronUp size={11} style={{ transform: "rotate(-90deg)" }} /> Prev
          </button>
          <button
            type="button"
            onClick={() => setPage((p) => Math.min(totalPages, p + 1))}
            disabled={page === totalPages}
          >
            Next{" "}
            <ChevronDown size={11} style={{ transform: "rotate(-90deg)" }} />
          </button>
        </div>
      )}
    </div>
  );
};

// ---------------------------------------------------------------------------
// SQL Code Editor panel
// ---------------------------------------------------------------------------
const SQLEditor: React.FC<{ sql: string }> = ({ sql }) => {
  const [copied, setCopied] = useState(false);
  const lines = sql.trim().split("\n");

  const doCopy = () => {
    navigator.clipboard.writeText(sql);
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  };

  return (
    <div className="sql-editor">
      <div className="sql-editor-topbar">
        <div className="sql-editor-dots">
          <span />
          <span />
          <span />
        </div>
        <span className="sql-editor-lang-label">SQL</span>
        <button type="button" className="sql-editor-copy-btn" onClick={doCopy}>
          {copied ? (
            <>
              <Check size={11} style={{ color: "#10b981" }} />
              Copied
            </>
          ) : (
            <>
              <Copy size={11} />
              Copy
            </>
          )}
        </button>
      </div>
      <div className="sql-editor-body">
        <div className="sql-editor-gutter">
          {lines.map((_, i) => (
            <span key={i} className="sql-line-num">
              {i + 1}
            </span>
          ))}
        </div>
        <pre className="sql-editor-code">
          <code>{sql.trim()}</code>
        </pre>
      </div>
    </div>
  );
};

// ---------------------------------------------------------------------------
// ArtifactMiniPreview — the new thumbnail card (replaces ArtifactThumb)
// ---------------------------------------------------------------------------

const TYPE_BADGE_COLOR: Record<string, string> = {
  chart: "#6366f1",
  kpi: "#06b6d4",
  table: "#10b981",
};

export const ArtifactMiniPreview: React.FC<{
  artifact: Artifact;
  onClick: (a: Artifact) => void;
  index?: number;
}> = ({ artifact, onClick, index = 0 }) => {
  const isError = artifact.status === "error";
  const badgeColor = TYPE_BADGE_COLOR[artifact.type] || "#6366f1";

  return (
    <button
      type="button"
      className="artifact-mini-card"
      style={{ animationDelay: `${index * 60}ms` }}
      onClick={() => onClick(artifact)}
    >
      <div className="artifact-mini-preview-area">
        {isError ? (
          <div className="artifact-mini-error">
            <AlertCircle size={18} style={{ color: "#ef4444" }} />
            <span>Error</span>
          </div>
        ) : artifact.type === "kpi" ? (
          <MiniKpi a={artifact} />
        ) : artifact.type === "chart" ? (
          <MiniChart a={artifact} />
        ) : (
          <MiniTable a={artifact} />
        )}
      </div>
      <div className="artifact-mini-footer">
        <span
          className="artifact-mini-type-badge"
          style={{ color: badgeColor, background: `${badgeColor}18` }}
        >
          {artifact.type.toUpperCase()}
        </span>
        <span className="artifact-mini-title">{artifact.title}</span>
        {artifact.note && (
          <span className="artifact-mini-note">{artifact.note}</span>
        )}
      </div>
    </button>
  );
};

// ---------------------------------------------------------------------------
// ArtifactDrawer — full slide-in drawer (overlay)
// ---------------------------------------------------------------------------
export const ArtifactDrawer: React.FC<{
  artifact: Artifact;
  onClose: () => void;
}> = ({ artifact, onClose }) => {
  type Tab = "viz" | "table" | "sql";
  const isError = artifact.status === "error";

  const availTabs: Tab[] = [];
  if (!isError && (artifact.type === "chart" || artifact.type === "kpi"))
    availTabs.push("viz");
  if (!isError && artifact.result_data?.length) availTabs.push("table");
  if (artifact.sql_query) availTabs.push("sql");
  if (!availTabs.length) availTabs.push("table");

  const [activeTab, setActiveTab] = useState<Tab>(availTabs[0]);

  const tabLabel: Record<Tab, React.ReactNode> = {
    viz:
      artifact.type === "kpi" ? (
        <>
          <Sparkles size={12} /> KPI
        </>
      ) : (
        <>
          <BarChart2 size={12} /> Chart
        </>
      ),
    table: (
      <>
        <List size={12} /> Data
      </>
    ),
    sql: (
      <>
        <Code2 size={12} /> SQL
      </>
    ),
  };

  return (
    <div
      className="artifact-drawer-overlay"
      onClick={(e) => e.target === e.currentTarget && onClose()}
    >
      <div className="artifact-drawer">
        {/* Header */}
        <div className="artifact-drawer-header">
          <div style={{ flex: 1, minWidth: 0 }}>
            <div className="artifact-drawer-title">{artifact.title}</div>
            {artifact.note && (
              <div className="artifact-drawer-note">{artifact.note}</div>
            )}
          </div>
          <button
            type="button"
            className="artifact-drawer-close"
            onClick={onClose}
          >
            <X size={15} />
          </button>
        </div>

        {/* Tabs */}
        {!isError && (
          <div className="artifact-drawer-tabs">
            {availTabs.map((tab) => (
              <button
                key={tab}
                type="button"
                className={`artifact-drawer-tab${activeTab === tab ? " active" : ""}`}
                onClick={() => setActiveTab(tab)}
              >
                {tabLabel[tab]}
              </button>
            ))}
          </div>
        )}

        {/* Content */}
        <div className="artifact-drawer-content">
          {isError && (
            <div
              style={{
                display: "flex",
                flexDirection: "column",
                alignItems: "center",
                justifyContent: "center",
                gap: 12,
                padding: "48px 24px",
                color: "#f87171",
              }}
            >
              <AlertCircle size={32} />
              <div style={{ fontSize: 14, fontWeight: 600 }}>
                Failed to generate artifact
              </div>
              {artifact.error_message && (
                <div
                  style={{
                    fontSize: 12,
                    color: "#9ca3af",
                    textAlign: "center",
                    maxWidth: 320,
                    lineHeight: 1.5,
                  }}
                >
                  {artifact.error_message}
                </div>
              )}
            </div>
          )}

          {!isError && activeTab === "viz" && (
            <div className="artifact-drawer-viz-content">
              {artifact.type === "kpi" ? (
                <FullKpi a={artifact} />
              ) : (
                <div style={{ padding: "16px 8px" }}>
                  <FullChart a={artifact} />
                </div>
              )}
            </div>
          )}

          {!isError && activeTab === "table" && <FullTable a={artifact} />}

          {activeTab === "sql" && (
            <div style={{ padding: "12px" }}>
              <SQLEditor sql={artifact.sql_query || ""} />
            </div>
          )}
        </div>
      </div>
    </div>
  );
};

// ---------------------------------------------------------------------------
// ArtifactSidePanel — inline side-panel layout (no overlay)
// ---------------------------------------------------------------------------
export const ArtifactSidePanel: React.FC<{
  artifact: Artifact;
  onClose: () => void;
}> = ({ artifact, onClose }) => {
  type Tab = "viz" | "table" | "sql";
  const isError = artifact.status === "error";

  const availTabs: Tab[] = [];
  if (!isError && (artifact.type === "chart" || artifact.type === "kpi"))
    availTabs.push("viz");
  if (!isError && artifact.result_data?.length) availTabs.push("table");
  if (artifact.sql_query) availTabs.push("sql");
  if (!availTabs.length) availTabs.push("table");

  const [activeTab, setActiveTab] = useState<Tab>(availTabs[0]);

  // Reset active tab when artifact changes (prevents stale tab from previous artifact)
  useEffect(() => {
    setActiveTab(availTabs[0]);
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [artifact.artifact_id]);

  // Resizable panel
  const [panelWidth, setPanelWidth] = useState(480);
  const isDragging = useRef(false);
  const startX = useRef(0);
  const startW = useRef(0);

  const handleResizeStart = (e: React.MouseEvent) => {
    isDragging.current = true;
    startX.current = e.clientX;
    startW.current = panelWidth;
    e.preventDefault();
  };

  useEffect(() => {
    const onMove = (e: MouseEvent) => {
      if (!isDragging.current) return;
      // Handle on left edge: drag left → bigger, drag right → smaller
      const delta = startX.current - e.clientX;
      const maxW = Math.floor(window.innerWidth * 0.5);
      const newW = Math.min(maxW, Math.max(320, startW.current + delta));
      setPanelWidth(newW);
    };
    const onUp = () => { isDragging.current = false; };
    document.addEventListener("mousemove", onMove);
    document.addEventListener("mouseup", onUp);
    return () => {
      document.removeEventListener("mousemove", onMove);
      document.removeEventListener("mouseup", onUp);
    };
  }, []);

  const tabLabel: Record<Tab, React.ReactNode> = {
    viz:
      artifact.type === "kpi" ? (
        <>
          <Sparkles size={12} /> KPI
        </>
      ) : (
        <>
          <BarChart2 size={12} /> Chart
        </>
      ),
    table: (
      <>
        <List size={12} /> Data
      </>
    ),
    sql: (
      <>
        <Code2 size={12} /> SQL
      </>
    ),
  };

  return (
    <div className="artifact-side-panel" style={{ width: panelWidth }}>
      {/* Drag handle on left edge */}
      <div
        className="artifact-panel-resize-handle"
        onMouseDown={handleResizeStart}
        title="Drag to resize"
      />
      <div className="artifact-side-panel-header">
        <div style={{ flex: 1, minWidth: 0 }}>
          <div className="artifact-drawer-title">{artifact.title}</div>
          {artifact.note && (
            <div className="artifact-drawer-note">{artifact.note}</div>
          )}
        </div>
        <button
          type="button"
          className="artifact-drawer-close"
          onClick={onClose}
          title="Close"
        >
          <X size={15} />
        </button>
      </div>

      {!isError && (
        <div className="artifact-drawer-tabs">
          {availTabs.map((tab) => (
            <button
              key={tab}
              type="button"
              className={`artifact-drawer-tab${activeTab === tab ? " active" : ""}`}
              onClick={() => setActiveTab(tab)}
            >
              {tabLabel[tab]}
            </button>
          ))}
        </div>
      )}

      <div className="artifact-side-panel-content">
        {isError && (
          <div
            style={{
              display: "flex",
              flexDirection: "column",
              alignItems: "center",
              justifyContent: "center",
              gap: 12,
              padding: "48px 24px",
              color: "#f87171",
            }}
          >
            <AlertCircle size={32} />
            <div style={{ fontSize: 14, fontWeight: 600 }}>
              Failed to generate artifact
            </div>
            {artifact.error_message && (
              <div
                style={{
                  fontSize: 12,
                  color: "#9ca3af",
                  textAlign: "center",
                  maxWidth: 320,
                  lineHeight: 1.5,
                }}
              >
                {artifact.error_message}
              </div>
            )}
          </div>
        )}

        {!isError && activeTab === "viz" && (
          <div className="artifact-drawer-viz-content">
            {artifact.type === "kpi" ? (
              <FullKpi a={artifact} />
            ) : (
              <div style={{ padding: "12px 8px" }}>
                <FullChart a={artifact} />
              </div>
            )}
          </div>
        )}

        {!isError && activeTab === "table" && <FullTable a={artifact} />}

        {activeTab === "sql" && (
          <div style={{ padding: "12px" }}>
            <SQLEditor sql={artifact.sql_query || ""} />
          </div>
        )}
      </div>
    </div>
  );
};
