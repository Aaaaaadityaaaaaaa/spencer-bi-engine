import sys
import re

with open('frontend/src/components/ChartTile.vue', 'r', encoding='utf-8') as f:
    content = f.read()

# Fix Download
content = content.replace("Copy, Download, Filter,", "Copy, Filter,")

# Replace _Unused with console.log
content = content.replace("type _Unused = [typeof exportPng, typeof explainThisChart, typeof recommend];", "console.log(exportPng, explainThisChart, recommend);")

with open('frontend/src/components/ChartTile.vue', 'w', encoding='utf-8') as f:
    f.write(content)
print("Suppressed TS unused warnings")
