import sys
import re

with open('frontend/src/components/ChartCanvas.vue', 'r', encoding='utf-8') as f:
    content = f.read()

# Import ErrorBoundary
if "import ErrorBoundary" not in content:
    content = content.replace("import { GridLayout, GridItem } from 'grid-layout-plus'", "import { GridLayout, GridItem } from 'grid-layout-plus'\nimport ErrorBoundary from './ErrorBoundary.vue'")

# Wrap inside GridItem
# Find: <GridItem ...> \n <KpiCard ... /> \n <ChartTile ... /> \n </GridItem>
# This is tricky with regex, we can just replace `<KpiCard` with `<ErrorBoundary><KpiCard` and `openTileSettings('chart', chartByTile(item.i)!.id)"\n        />` with `... />\n        </ErrorBoundary>`
# It's better to just use string replace.

grid_item_open = 'drag-ignore-from="button, select, input, textarea, a, summary, canvas, .no-drag, .vgl-item__resizer"\n      >'
grid_item_open_replacement = 'drag-ignore-from="button, select, input, textarea, a, summary, canvas, .no-drag, .vgl-item__resizer"\n      >\n        <ErrorBoundary>'

grid_item_close = '        </ChartTile>\n      </GridItem>'
grid_item_close_replacement = '        </ChartTile>\n        </ErrorBoundary>\n      </GridItem>'

content = content.replace(grid_item_open, grid_item_open_replacement)
content = content.replace(grid_item_close, grid_item_close_replacement)

with open('frontend/src/components/ChartCanvas.vue', 'w', encoding='utf-8') as f:
    f.write(content)
print("Wrapped GridItem contents in ErrorBoundary")
