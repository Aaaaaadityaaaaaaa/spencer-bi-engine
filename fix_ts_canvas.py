import sys
import re

with open('frontend/src/components/ChartCanvas.vue', 'r', encoding='utf-8') as f:
    content = f.read()

# Fix startRenameSaved signature
content = content.replace("function startRenameSaved(id: string, name: string): void {", "function startRenameSaved(id: number, name: string): void {")

# Fix removeSaved signature
content = content.replace("function removeSaved(d: { id: string; name: string }): void {", "function removeSaved(d: { id: number; name: string }): void {")

# Fix loadFromServer TS6133
content = content.replace("const { dashboards, saveDashboard, loadDashboard, renameDashboard, deleteDashboard, loadFromServer } = useDashboards()", "const { dashboards, saveDashboard, loadDashboard, renameDashboard, deleteDashboard } = useDashboards()")

with open('frontend/src/components/ChartCanvas.vue', 'w', encoding='utf-8') as f:
    f.write(content)
print("Fixed TS errors in ChartCanvas")
