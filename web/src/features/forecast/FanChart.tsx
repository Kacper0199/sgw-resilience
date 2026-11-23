import { CustomChart } from "echarts/charts";
import { GridComponent, TooltipComponent } from "echarts/components";
import * as echarts from "echarts/core";
import { SVGRenderer } from "echarts/renderers";
import ReactEChartsCore from "echarts-for-react/lib/core";
import { useMemo } from "react";
import { useChartColors } from "@/components/sgw/useChartColors";
import { useThemeColors } from "../map/useThemeColors";
import { count, countyLabel } from "./format";
import type { CountyFan } from "./types";

echarts.use([CustomChart, GridComponent, TooltipComponent, SVGRenderer]);

const ROW_PX = 44;
const BANDS = [
  { lo: 1, hi: 7, share: 0.2, tone: "bandWide" },
  { lo: 2, hi: 6, share: 0.42, tone: "bandMid" },
  { lo: 3, hi: 5, share: 0.7, tone: "bandCore" },
] as const;

interface Props {
  counties: CountyFan[];
}

const LEGEND = [
  { label: "50% of scenarios", band: BANDS[2] },
  { label: "80%", band: BANDS[1] },
  { label: "95%", band: BANDS[0] },
] as const;

/** One swatch per bar thickness, thickest first, then the median tick. */
function FanLegend() {
  const chart = useChartColors();
  return (
    <ul
      aria-label="How to read the bars"
      className="m-0 flex list-none flex-wrap items-center gap-x-4 gap-y-1 p-0 text-[12px] text-muted"
      data-testid="fan-legend"
    >
      {LEGEND.map(({ label, band }) => (
        <li key={label} className="inline-flex items-center gap-1.5">
          <span
            aria-hidden
            className="inline-block w-5 rounded-[1px]"
            style={{ background: chart[band.tone], height: `${Math.round(band.share * 16)}px` }}
          />
          {label}
        </li>
      ))}
      <li className="inline-flex items-center gap-1.5">
        <span aria-hidden className="inline-block h-3.5 w-0.5" style={{ background: chart.median }} />
        Median
      </li>
    </ul>
  );
}

/** Nested 50%, 80% and 95% ranges per county, with the median as a tick. The unit is on the axis. */
export function FanChart({ counties }: Props) {
  const c = useThemeColors();
  const chart = useChartColors();
  const option = useMemo(() => {
    const rows = counties.map((f, i) => [i, f.q0025, f.q0100, f.q0250, f.q0500, f.q0750, f.q0900, f.q0975]);
    return {
      animation: false,
      textStyle: { fontFamily: "IBM Plex Sans, system-ui, sans-serif", color: c.ink },
      grid: { left: 124, right: 24, top: 56, bottom: 8 },
      tooltip: {
        trigger: "item",
        confine: true,
        backgroundColor: c.surface,
        borderColor: c.coast,
        textStyle: { color: c.ink, fontSize: 12 },
        formatter: (p: { value: number[] }) => {
          const f = counties[p.value[0] as number] as CountyFan;
          return [
            `<strong>${countyLabel(f.name, f.fips)}</strong>`,
            `${count(f.customers)} customers`,
            `Median ${count(f.q0500)}`,
            `50% range ${count(f.q0250)} to ${count(f.q0750)}`,
            `80% range ${count(f.q0100)} to ${count(f.q0900)}`,
            `95% range ${count(f.q0025)} to ${count(f.q0975)}`,
          ].join("<br/>");
        },
      },
      xAxis: {
        type: "value",
        position: "top",
        name: "Customers without power at the peak",
        nameLocation: "middle",
        nameGap: 32,
        nameTextStyle: { color: c.muted, fontSize: 12 },
        axisLabel: { color: c.muted, fontSize: 12, formatter: (v: number) => count(v) },
        axisTick: { show: true, lineStyle: { color: c.coast } },
        splitLine: { lineStyle: { color: c.coast, opacity: 0.5 } },
        axisLine: { lineStyle: { color: c.coast } },
      },
      yAxis: {
        type: "category",
        inverse: true,
        data: counties.map((f) => countyLabel(f.name, f.fips)),
        axisTick: { show: false },
        axisLine: { lineStyle: { color: c.coast } },
        axisLabel: { color: c.ink, fontSize: 12 },
      },
      series: [
        {
          type: "custom",
          encode: { x: [1, 2, 3, 4, 5, 6, 7], y: 0 },
          data: rows,
          renderItem: (
            _params: unknown,
            api: {
              value: (i: number) => number;
              coord: (v: [number, number]) => [number, number];
              size: (v: [number, number]) => [number, number];
            },
          ) => {
            const cat = api.value(0);
            const h = api.size([0, 1])[1];
            const y = api.coord([0, cat])[1];
            const x = (i: number) => api.coord([api.value(i), cat])[0];
            const rects = BANDS.map((b) => ({
              type: "rect",
              shape: {
                x: x(b.lo),
                y: y - (h * b.share) / 2,
                width: Math.max(1, x(b.hi) - x(b.lo)),
                height: h * b.share,
              },
              style: { fill: chart[b.tone] },
            }));
            const mid = x(4);
            return {
              type: "group",
              children: [
                ...rects,
                {
                  type: "line",
                  shape: { x1: mid, y1: y - h * 0.38, x2: mid, y2: y + h * 0.38 },
                  style: { stroke: chart.median, lineWidth: 2 },
                },
              ],
            };
          },
        },
      ],
    };
  }, [counties, c, chart]);

  return (
    <div>
      <FanLegend />
      <div
        role="img"
        aria-label="Range of customers without power at the peak, per county"
        data-testid="fan-chart"
      >
        <ReactEChartsCore
          echarts={echarts}
          option={option}
          notMerge
          opts={{ renderer: "svg" }}
          style={{ height: counties.length * ROW_PX + 64, width: "100%" }}
        />
      </div>
    </div>
  );
}
