// ECharts lifecycle in one place (Phase 5 / TASK-011).
//
// ADR-005 chose hand-built ECharts over PyGWalker, and there is no Vue wrapper in the
// dependency list -- so a tile talks to the raw imperative API. That API needs care
// (init once, dispose on unmount, resize on container change) and Canvas v2 will have
// many tiles, so the lifecycle lives here instead of in every component.
//
// Imports are MODULAR (echarts/core + only the charts/components actually used) rather
// than `import * as echarts from 'echarts'`, which would pull the entire ~1 MB bundle
// including maps, GL and every chart type we do not render.
import { onActivated, onBeforeUnmount, onMounted, watch } from 'vue'
import type { Ref } from 'vue'
import * as echarts from 'echarts/core'
import { BarChart, LineChart, PieChart, HeatmapChart, TreemapChart, FunnelChart } from 'echarts/charts'
import {
  DatasetComponent,
  GridComponent,
  LegendComponent,
  TooltipComponent,
  VisualMapComponent,
} from 'echarts/components'
import { CanvasRenderer } from 'echarts/renderers'
import type { EChartsCoreOption, EChartsType } from 'echarts/core'

// Registered once at module scope (ES modules are singletons), not per component.
echarts.use([
  BarChart,
  LineChart,
  PieChart,
  HeatmapChart,   // TASK-025: 2-D dimension × series grid
  TreemapChart,   // TASK-025: 1-D nested-area alternative to pie
  FunnelChart,    // TASK-025: 1-D ranked-stage view
  GridComponent,
  TooltipComponent,
  LegendComponent,
  VisualMapComponent, // TASK-025: heatmap colour scale
  DatasetComponent,
  CanvasRenderer,
])

/**
 * Bind an ECharts instance to `el`, driven by `option`.
 *
 * - `setOption(opt, true)` uses notMerge, so switching chart type (bar -> pie) fully
 *   replaces the previous config instead of leaving orphaned axes behind.
 * - A null option clears the canvas (no data / an errored tile) without disposing,
 *   so the instance survives to be reused.
 * - A ResizeObserver handles container resizes (sidebar collapse, window resize).
 * - `onActivated` re-resizes after a <keep-alive> tab switch: a chart initialised or
 *   resized while its view was cached can otherwise come back at the wrong size.
 */
export interface EchartHandle {
  /** Current chart as a PNG data URL (2× for a crisp export), or null before init. */
  getDataURL: () => string | null
}

export function useEchart(
  el: Ref<HTMLElement | null>,
  option: Ref<EChartsCoreOption | null>,
  onClick?: (dataIndex: number) => void,
): EchartHandle {
  let chart: EChartsType | null = null
  let observer: ResizeObserver | null = null

  function render(): void {
    const host = el.value
    if (!host) return
    if (!chart) {
      chart = echarts.init(host)
      // Cross-filter: report a bar/slice click by data index. The caller maps the index
      // back to the raw dimension key -- `params.name` is the stringified label and loses
      // null / numeric identity, so the index is what we hand back.
      if (onClick) {
        chart.on('click', (params) => {
          const i = (params as { dataIndex?: number }).dataIndex
          if (typeof i === 'number') onClick(i)
        })
      }
      observer = new ResizeObserver(() => chart?.resize())
      observer.observe(host)
    }
    if (option.value) chart.setOption(option.value, true)
    else chart.clear()
  }

  onMounted(render)
  watch(option, render)
  onActivated(() => chart?.resize())

  onBeforeUnmount(() => {
    observer?.disconnect()
    observer = null
    chart?.dispose() // frees the canvas + ECharts' internal listeners
    chart = null
  })

  // Snapshot the live canvas. White background (not transparent) so the exported PNG
  // reads correctly on any surface; 2× pixelRatio keeps text crisp when embedded.
  function getDataURL(): string | null {
    return chart
      ? chart.getDataURL({ type: 'png', pixelRatio: 2, backgroundColor: '#ffffff' })
      : null
  }

  return { getDataURL }
}
