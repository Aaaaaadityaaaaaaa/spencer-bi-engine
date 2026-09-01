import sys
import re

with open('frontend/src/components/ChartTile.vue', 'r', encoding='utf-8') as f:
    content = f.read()

# Fix Download
content = content.replace("Copy, Download, GripVertical,", "Copy, GripVertical,")

with open('frontend/src/components/ChartTile.vue', 'w', encoding='utf-8') as f:
    f.write(content)
print("Suppressed TS unused warnings")
