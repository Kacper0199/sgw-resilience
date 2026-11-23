import { BarChart, LineChart } from "echarts/charts";
import { GridComponent, MarkAreaComponent, MarkLineComponent, TooltipComponent } from "echarts/components";
import * as echarts from "echarts/core";
import { SVGRenderer } from "echarts/renderers";
import ReactEChartsCore from "echarts-for-react/lib/core";
import { useMemo, useSyncExternalStore } from "react";
import { formatET } from "@/lib/time";
import { dayET, localDay } from "./hazardModel";
import type { HeatView, WildfireView } from "./hazardTypes";

echarts.use([
  BarChart,
  LineChart,
  GridComponent,
  TooltipComponent,
  MarkLineComponent,
  MarkAreaComponent,
  SVGRenderer,
]);

const FONT = "IBM Plex Sans, system-ui, sans-serif";

/** The hourly category at or before a time, as it appears on the axis. */
function onHour(view: WildfireView, iso: string): string {
  const t = Date.parse(iso);
  return view.hours.reduce(
    (best, h) => (Date.parse(h.t_utc) <= t ? h.t_utc : best),
    view.hours[0]?.t_utc ?? iso,
  );
}

const css = (name: string) => getComputedStyle(document.documentElement).getPropertyValue(name).trim();

const readColors = () => ({
  ink: css("--ink"),
  muted: css("--muted"),
  coast: css("--hair-strong"),
  surface: css("--surface"),
  bar: css("--chart-band-wide"),
  line: css("--chart-1"),
  hot: css("--chart-3"),
});

let colors: { theme: string; value: ReturnType<typeof readColors> } | null = null;

const snapshot = () => {
  const theme = document.documentElement.dataset.theme ?? "";
  if (colors?.theme !== theme) colors = { theme, value: readColors() };
  return colors.value;
};

const subscribe = (notify: () => void) => {
  const observer = new MutationObserver(() => {
    colors = null;
    notify();
  });
  observer.observe(document.documentElement, { attributes: true, attributeFilter: ["data-theme"] });
  return () => observer.disconnect();
};

function useAxis() {
  const c = useSyncExternalStore(subscribe, snapshot, snapshot);
  return useMemo(
    () => ({
      c,
      label: { color: c.muted, fontSize: 12, fontFamily: FONT },
      line: { lineStyle: { color: c.coast } },
      split: { lineStyle: { color: c.coast, opacity: 0.35 } },
      tooltip: {
        confine: true,
        backgroundColor: c.surface,
        borderColor: c.coast,
        textStyle: { color: c.ink, fontSize: 12, fontFamily: FONT },
      },
    }),
    [c],
  );
}

/** Station-mean daily high for the month, hot days in amber, the trigger threshold as a dashed line. */
export function HeatChart({ view, height }: { view: HeatView; height: number }) {
  const a = useAxis();
  const option = useMemo(
    () => ({
      animation: false,
      textStyle: { fontFamily: FONT, color: a.c.ink },
      grid: { left: 44, right: 96, top: 12, bottom: 24 },
      tooltip: {
        ...a.tooltip,
        trigger: "axis",
        axisPointer: { type: "shadow" },
        formatter: (p: { dataIndex: number }[]) => {
          const d = view.days[p[0]?.dataIndex ?? 0];
          return d
            ? `${localDay(d.day)}: <strong>${d.tmax_c.toFixed(1)} °C</strong>${d.hot ? ", hot day" : ""}`
            : "";
        },
      },
      xAxis: {
        type: "category",
        data: view.days.map((d) => localDay(d.day)),
        axisLabel: { ...a.label, interval: 4 },
        axisTick: { show: false },
        axisLine: a.line,
      },
      yAxis: {
        type: "value",
        min: 26,
        max: 38,
        interval: 4,
        axisLabel: { ...a.label, formatter: "{value} °C" },
        splitLine: a.split,
      },
      series: [
        {
          type: "bar",
          barWidth: "62%",
          data: view.days.map((d) => ({
            value: d.tmax_c,
            itemStyle: { color: d.hot ? a.c.hot : a.c.bar },
          })),
          markLine: {
            silent: true,
            symbol: "none",
            lineStyle: { color: a.c.ink, type: "dashed", width: 1.25 },
            label: {
              position: "end",
              color: a.c.ink,
              fontSize: 12,
              fontFamily: FONT,
              formatter: `Trigger ${view.threshold_c.toFixed(1)} °C`,
            },
            data: [{ yAxis: view.threshold_c }],
          },
        },
      ],
    }),
    [view, a],
  );
  return (
    <div
      role="img"
      aria-label={`Daily high, mean of ${view.stations.length} stations, July 2024, against the ${view.threshold_c.toFixed(1)} °C trigger`}
      data-testid="heat-chart"
    >
      <ReactEChartsCore
        echarts={echarts}
        option={option}
        notMerge
        opts={{ renderer: "svg" }}
        style={{ height }}
      />
    </div>
  );
}

/** Hourly Fosberg index at the station, Red Flag periods shaded, the trigger level dashed, fire discoveries marked. */
export function FireChart({ view, height }: { view: WildfireView; height: number }) {
  const a = useAxis();
  const option = useMemo(
    () => ({
      animation: false,
      textStyle: { fontFamily: FONT, color: a.c.ink },
      grid: { left: 36, right: 84, top: 22, bottom: 24 },
      tooltip: {
        ...a.tooltip,
        trigger: "axis",
        formatter: (p: { dataIndex: number }[]) => {
          const h = view.hours[p[0]?.dataIndex ?? 0];
          return h
            ? `${dayET(h.t_utc)}, ${formatET(h.t_utc)}<br/>Fire index <strong>${h.ffwi.toFixed(0)}</strong>, humidity ${h.rh_pct.toFixed(0)}%${h.red_flag ? "<br/>Red Flag" : ""}`
            : "";
        },
      },
      xAxis: {
        type: "category",
        data: view.hours.map((h) => h.t_utc),
        boundaryGap: false,
        axisLabel: {
          ...a.label,
          interval: (i: number, value: string) =>
            i === 0 || dayET(value) !== dayET(view.hours[i - 1]?.t_utc ?? value),
          formatter: (value: string) => dayET(value),
        },
        axisTick: { show: false },
        axisLine: a.line,
      },
      yAxis: {
        type: "value",
        min: 0,
        max: 80,
        interval: 20,
        axisLabel: a.label,
        splitLine: a.split,
      },
      series: [
        {
          type: "line",
          showSymbol: false,
          lineStyle: { color: a.c.line, width: 1.5 },
          itemStyle: { color: a.c.line },
          data: view.hours.map((h) => h.ffwi),
          markArea: {
            silent: true,
            itemStyle: { color: a.c.hot, opacity: 0.22 },
            data: view.episodes.map((e) => [
              { xAxis: onHour(view, e.start_utc) },
              { xAxis: onHour(view, e.end_utc) },
            ]),
          },
          markLine: {
            silent: true,
            symbol: "none",
            data: [
              {
                yAxis: view.ffwi_min,
                lineStyle: { color: a.c.ink, type: "dashed", width: 1.25 },
                label: {
                  position: "end",
                  color: a.c.ink,
                  fontSize: 12,
                  fontFamily: FONT,
                  formatter: `Trigger ${view.ffwi_min.toFixed(0)}`,
                },
              },
              ...view.fires.slice(0, 1).map((f) => ({
                xAxis: onHour(view, f.discovered_utc),
                lineStyle: { color: a.c.muted, type: "solid", width: 1 },
                label: {
                  position: "end",
                  color: a.c.muted,
                  fontSize: 12,
                  fontFamily: FONT,
                  formatter: `${f.name} fire found`,
                },
              })),
            ],
          },
        },
      ],
    }),
    [view, a],
  );
  return (
    <div
      role="img"
      aria-label={`Hourly fire weather index at ${view.station} with Red Flag periods and the trigger level ${view.ffwi_min}`}
      data-testid="fire-chart"
    >
      <ReactEChartsCore
        echarts={echarts}
        option={option}
        notMerge
        opts={{ renderer: "svg" }}
        style={{ height }}
      />
    </div>
  );
}
