import sys
import re

with open('frontend/src/components/ChartCanvas.vue', 'r', encoding='utf-8') as f:
    content = f.read()

# Replace `/>\n      </GridItem>` with `/>\n        </ErrorBoundary>\n      </GridItem>`
old_close = """          @open-settings="openTileSettings('chart', chartByTile(item.i)!.id)"
        />
      </GridItem>"""

new_close = """          @open-settings="openTileSettings('chart', chartByTile(item.i)!.id)"
        />
        </ErrorBoundary>
      </GridItem>"""

content = content.replace(old_close, new_close)

with open('frontend/src/components/ChartCanvas.vue', 'w', encoding='utf-8') as f:
    f.write(content)
print("Fixed ErrorBoundary closing tag")
