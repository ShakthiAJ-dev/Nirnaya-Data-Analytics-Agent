# Nirnaya Artifact Contracts � Master Reference

> **Single source of truth for FE engineers.**
> Every field documented here is enforced by BE Pydantic schemas and the LLM worker prompt.
> The FE can rely on these shapes without defensive coding for unknown keys.

---

## Overview

Every artifact the agent produces has this top-level shape (from the `artifacts` Postgres table and the WS `final` event):

```ts
{
  artifact_id:   string;          // UUID
  type:          "kpi" | "chart" | "table";
  title:         string;          // LLM-generated title
  note:          string;          // One-line insight / summary
  key_numbers:   object;          // Type-specific (see per-type sections below)
  status:        "fresh" | "error";
  error_message: string | null;
  config:        object;          // Type-specific � the main contract (see below)
  result_data:   object[];        // Raw SQL rows (capped at 1000)
  sql_query:     string;          // The SQL that produced this artifact
}
```

The `config` JSONB column is where the rendering contract lives. The shape of `config` is strictly determined by `type`.

---

## 1. Chart Artifacts (`type = "chart"`)

### 1.1 `config` shape

```ts
config: {
  chart_family:  ChartFamily;
  chart_type:    ChartType;
  encoding:      ChartEncoding;
  chart_config:  ChartConfig;     // may be {} if LLM omitted � use defaults
}
```

### 1.2 Chart Families & Types

| `chart_family` | Valid `chart_type` values |
|---|---|
| `cartesian_xy` | `line` `bar` `grouped_bar` `stacked_bar` `area` `scatter` `bubble` `histogram` `box_plot` |
| `part_to_whole` | `donut` `treemap` |
| `sequential_delta` | `waterfall` |
| `category_matrix` | `heatmap` |
| `flow_conversion` | `funnel` |

> chart_type is always consistent with chart_family.

### 1.3 ChartEncoding � required fields per chart type

| `chart_type` | `x` | `y` | `series` | `size` | `category` | `value` |
|---|---|---|---|---|---|---|
| `line` | REQ | REQ | opt | � | � | � |
| `bar` | REQ | REQ | opt | � | � | � |
| `grouped_bar` | REQ | REQ | REQ | � | � | � |
| `stacked_bar` | REQ | REQ | REQ | � | � | � |
| `area` | REQ | REQ | opt | � | � | � |
| `scatter` | REQ | REQ | opt | � | � | � |
| `bubble` | REQ | REQ | � | REQ | � | � |
| `histogram` | REQ | � | � | � | � | � |
| `box_plot` | REQ | REQ | opt | � | � | � |
| `donut` | � | � | � | � | REQ | REQ |
| `treemap` | � | � | � | � | REQ | REQ |
| `waterfall` | REQ | REQ | � | � | � | � |
| `heatmap` | REQ | REQ | � | � | � | REQ |
| `funnel` | � | � | � | � | REQ | REQ |

### 1.4 ChartConfig � display hints

| Field | Type | Default | Notes |
|---|---|---|---|
| `orientation` | `"vertical"` \| `"horizontal"` | `"vertical"` | `"horizontal"` for bar with long labels or >6 categories |
| `show_legend` | `boolean` | `true` | `false` when single series |
| `show_data_labels` | `boolean` | `false` | `true` for donut, waterfall, funnel, small bar |
| `show_grid` | `boolean` | `true` | |
| `sort_order` | `"asc"` \| `"desc"` \| `"none"` | `"none"` | `"desc"` for ranked bar/donut/funnel |
| `stack_type` | `"value"` \| `"percent"` | `"value"` | `stacked_bar` only; `"percent"` for 100% stack |
| `line_style` | `"solid"` \| `"dashed"` \| `"dotted"` | `"solid"` | `"dashed"` for forecasts |
| `fill_opacity` | `number` (0�1) | absent | area charts: 0.15�0.3 |
| `x_axis_label` | `string` | absent | human-readable axis label |
| `y_axis_label` | `string` | absent | human-readable axis label |

### 1.5 key_numbers for charts

Free dict � summary numbers for the narrative. FE does not render these visually.

```json
{ "total": 482130.5, "top_category": "EU", "period": "Q1 2024", "pct_of_total": 43.2 }
```

---

## 2. KPI Artifacts (`type = "kpi"`)

### 2.1 `config` shape

```ts
config: {
  card_type:      "single_value" | "value_with_delta" | "value_with_target";
  format:         "currency" | "number" | "percent";
  display_config: KPIDisplayConfig;  // may be {} � use defaults
}
```

### 2.2 KPI Card Types & key_numbers shapes

#### `card_type: "single_value"`
```ts
key_numbers: { value: number }
```
FE renders: Large number + title + note. No comparison indicator.

---

#### `card_type: "value_with_delta"`
```ts
key_numbers: {
  value:     number;         // current period � ALWAYS present
  delta_pct: number;         // signed % change (+5.2 = +5.2%) � ALWAYS present
  delta_abs: number | null;  // absolute change � optional
}
```
FE renders: Large value + coloured arrow badge + comparison_label from display_config.

**Arrow colour logic:**
- `delta_pct > 0` + `trend_direction="up_is_good"` ? green ?
- `delta_pct < 0` + `trend_direction="up_is_good"` ? red ?
- `delta_pct > 0` + `trend_direction="down_is_good"` ? red ? (bad)
- `delta_pct < 0` + `trend_direction="down_is_good"` ? green ? (good)

---

#### `card_type: "value_with_target"`
```ts
key_numbers: {
  value:     number;         // actual / current value � ALWAYS present
  target:    number;         // goal / quota � ALWAYS present
  delta_pct: number | null;  // ((value-target)/target)*100 � optional
}
```
FE renders: Large value + progress bar toward target + optional pct.

- `value >= target` ? green progress bar / ? icon
- `value < target` ? amber in-progress bar

---

### 2.3 `format` rendering

| `format` | FE applies |
|---|---|
| `currency` | prefix + 2dp + thousands separator (e.g. `$48,213.50`) |
| `percent` | value + `%` + 2dp (e.g. `34.21%`) |
| `number` | decimal_places dp + thousands separator (e.g. `12,847`) |

### 2.4 KPIDisplayConfig

| Field | Type | Default | Notes |
|---|---|---|---|
| `prefix` | `string` | `"$"` if currency, else `""` | Currency symbol |
| `suffix` | `string` | `"%"` if percent, else `""` | `"K"`/`"M"`/`"B"` for large numbers |
| `decimal_places` | `number` | `2` | `0` for counts/integers |
| `trend_direction` | `"up_is_good"` \| `"down_is_good"` | `"up_is_good"` | Controls arrow colour |
| `comparison_label` | `string` | absent | e.g. `"vs last month"` |
| `color_theme` | `"default"` \| `"positive"` \| `"negative"` \| `"warning"` | `"default"` | Card accent colour |

**`color_theme` accent colours:**

| Value | Colour | Use when |
|---|---|---|
| `"default"` | Neutral (blue/accent) | Most KPIs |
| `"positive"` | Green | Confirmed above target/trend |
| `"negative"` | Red | Confirmed below target/declining |
| `"warning"` | Amber | Approaching a threshold |

**Number formatting with suffix:**
- `format=currency` + `suffix="M"` ? `$48.2M`
- `format=number` + `suffix="K"` ? `12.8K`
- `format=percent` ? suffix ignored (`%` always applied)

---

## 3. Table Artifacts (`type = "table"`)

### 3.1 `config` shape

```ts
config: {
  columns:      TableColumnConfig[];
  table_config: TableConfig;          // may be {} � use defaults
}
```

### 3.2 TableColumnConfig

| Field | Type | Default | Notes |
|---|---|---|---|
| `field` | `string` | � | Exact key in result_data rows |
| `label` | `string` | � | Display label (Title Case) |
| `format` | `"currency"` \| `"number"` \| `"percent"` \| `"date"` \| `null` | `null` | |
| `align` | `"left"` \| `"center"` \| `"right"` \| absent | auto | See auto-align table |
| `sortable` | `boolean` | `true` | |
| `width_hint` | `"xs"` \| `"sm"` \| `"md"` \| `"lg"` \| `"xl"` \| absent | auto-size | |

**Auto-align defaults:**

| `format` | Auto align |
|---|---|
| `currency` | `right` |
| `number` | `right` |
| `percent` | `right` |
| `date` | `center` |
| `null` (text) | `left` |

**width_hint reference:**

| Value | Approx | Best for |
|---|---|---|
| `xs` | ~60px | id, flag, boolean |
| `sm` | ~100px | short codes, integer counts |
| `md` | ~160px | most columns (default) |
| `lg` | ~240px | description fields, names |
| `xl` | ~360px | full-text, URLs |

### 3.3 TableConfig

| Field | Type | Default | Notes |
|---|---|---|---|
| `default_sort_column` | `string \| null` | `null` (first col) | Most important metric field |
| `default_sort_direction` | `"asc"` \| `"desc"` | `"desc"` | |
| `show_row_numbers` | `boolean` | `false` | `true` for leaderboards |
| `enable_search` | `boolean` | `false` | `true` for lookup tables |
| `page_size` | `number \| null` | `null` | `25` when row_count > 50 |

---

## 4. Error Artifacts

```ts
{
  type:          "kpi" | "chart" | "table",
  status:        "error",
  error_message: string,
  config:        {},
  result_data:   [],
  key_numbers:   {},
}
```

FE renders: error state card with `title` + `error_message`.

---

## 5. result_data

- Array of plain objects; keys = SQL column aliases.
- Max **1000 rows** (BE enforced).
- Keys match `config.columns[*].field` (tables) or `config.encoding.*` (charts) exactly.

---

## 6. Encoding Quick Reference

```
chart_type     family              x   y   series  size  category  value
--------------------------------------------------------------------------
line           cartesian_xy        R   R   opt     -     -         -
bar            cartesian_xy        R   R   opt     -     -         -
grouped_bar    cartesian_xy        R   R   REQ     -     -         -
stacked_bar    cartesian_xy        R   R   REQ     -     -         -
area           cartesian_xy        R   R   opt     -     -         -
scatter        cartesian_xy        R   R   opt     -     -         -
bubble         cartesian_xy        R   R   -       REQ   -         -
histogram      cartesian_xy        R   -   -       -     -         -
box_plot       cartesian_xy        R   R   opt     -     -         -
donut          part_to_whole       -   -   -       -     REQ       REQ
treemap        part_to_whole       -   -   -       -     REQ       REQ
waterfall      sequential_delta    R   R   -       -     -         -
heatmap        category_matrix     R   R   -       -     -         REQ
funnel         flow_conversion     -   -   -       -     REQ       REQ
(R=required, opt=optional, -=omit/null)
```

---

## 7. Supabase Migration SQL (run once in SQL editor)

```sql
-- Fix message_id FK: SET NULL ? CASCADE so deleting a turn deletes its artifacts
ALTER TABLE public.artifacts
  DROP CONSTRAINT IF EXISTS artifacts_message_id_fkey;

ALTER TABLE public.artifacts
  ADD CONSTRAINT artifacts_message_id_fkey
    FOREIGN KEY (message_id)
    REFERENCES public.chat_messages(id)
    ON DELETE CASCADE;
```

---

*Source of truth: tools_worker.py Pydantic schemas + prompts.py ARTIFACT CONTRACT RULES.*
