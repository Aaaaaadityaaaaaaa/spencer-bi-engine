import sys

with open('frontend/src/components/TableSwitcher.vue', 'r', encoding='utf-8') as f:
    content = f.read()
content = content.replace("Plus, Database, X, Star, Palette", "Plus, Database, X, Star")
with open('frontend/src/components/TableSwitcher.vue', 'w', encoding='utf-8') as f:
    f.write(content)

with open('frontend/src/components/ChartTile.vue', 'r', encoding='utf-8') as f:
    content = f.read()
content = content.replace("Copy, Download, Filter, ", "Copy, Filter, ")
content = content.replace("async function exportPng()", "// async function exportPng()")
content = content.replace("async function explainThisChart()", "// async function explainThisChart()")
content = content.replace("async function recommend()", "// async function recommend()")
with open('frontend/src/components/ChartTile.vue', 'w', encoding='utf-8') as f:
    f.write(content)
print("Fixed remaining TS errors")
