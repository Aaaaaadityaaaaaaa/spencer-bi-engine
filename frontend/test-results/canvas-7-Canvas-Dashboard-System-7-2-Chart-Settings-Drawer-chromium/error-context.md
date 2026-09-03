# Instructions

- Following Playwright test failed.
- Explain why, be concise, respect Playwright best practices.
- Provide a snippet of code with the fix, if possible.

# Test info

- Name: canvas.spec.ts >> 7. Canvas & Dashboard System >> 7.2 Chart Settings Drawer
- Location: e2e\canvas.spec.ts:47:3

# Error details

```
Test timeout of 30000ms exceeded.
```

# Page snapshot

```yaml
- generic [ref=e3]:
  - complementary [ref=e4]:
    - generic [ref=e5]:
      - generic [ref=e6]: S
      - generic [ref=e7]: Spencer
    - navigation [ref=e8]:
      - link "Table" [ref=e9] [cursor=pointer]:
        - /url: /table
      - link "Model" [ref=e13] [cursor=pointer]:
        - /url: /model
      - link "Canvas" [ref=e20] [cursor=pointer]:
        - /url: /canvas
      - link "Query Engine" [ref=e25] [cursor=pointer]:
        - /url: /query
      - link "Settings" [ref=e31] [cursor=pointer]:
        - /url: /settings
    - generic [ref=e36]:
      - button "Collapse" [ref=e37] [cursor=pointer]
      - generic [ref=e42]:
        - generic [ref=e43]:
          - generic [ref=e44]: C
          - generic [ref=e45]: canvas_test_1788465752212@example.com
        - button "Sign out" [ref=e46] [cursor=pointer]
  - main [ref=e50]:
    - generic [ref=e51]:
      - generic [ref=e52]:
        - heading "Canvas" [level=2] [ref=e53]
        - generic "Active table" [ref=e54]: 5d462f63
      - generic [ref=e56]:
        - button "Search ⌘K" [ref=e57] [cursor=pointer]:
          - generic [ref=e61]: Search
          - generic [ref=e62]: ⌘K
        - button "Keyboard shortcuts" [ref=e64] [cursor=pointer]
        - button "Undo last transform (⌘Z)" [disabled] [ref=e67]
        - button "Redo transform (⇧⌘Z)" [disabled] [ref=e71]
    - generic [ref=e75]:
      - generic [ref=e76]:
        - generic [ref=e77]: Datasets
        - button "dirty_data primary" [ref=e85] [cursor=pointer]:
          - text: dirty_data
          - generic [ref=e86]: primary
      - generic [ref=e87]:
        - generic "Change Theme Color" [ref=e88]:
          - textbox [ref=e89] [cursor=pointer]: "#83bfc8"
          - generic [ref=e91]: 83bfc8
        - button "Add Dataset" [ref=e92] [cursor=pointer]
    - generic [ref=e96]:
      - generic [ref=e97]:
        - generic [ref=e98]:
          - heading "Dashboard" [level=2] [ref=e99]
          - paragraph [ref=e105]: Live over all 6 rows — aggregated server-side.
        - generic [ref=e106]:
          - button "Saved" [ref=e107] [cursor=pointer]
          - button "Tell the story" [ref=e111] [cursor=pointer]
          - button "Refresh" [ref=e115] [cursor=pointer]
          - button "Present" [ref=e121] [cursor=pointer]
          - button "PNG" [ref=e127] [cursor=pointer]
          - button "PDF" [ref=e133] [cursor=pointer]
          - button "Settings" [ref=e138] [cursor=pointer]
      - generic [ref=e142]:
        - generic [ref=e143] [cursor=pointer]:
          - generic [ref=e144]: Page 1
          - button "Rename page" [ref=e145]
        - button "Page" [ref=e149] [cursor=pointer]
      - generic [ref=e151]:
        - generic [ref=e153]:
          - generic [ref=e155]:
            - generic "Drag to move" [ref=e156]
            - generic "Total rows" [ref=e164]
          - generic "6" [ref=e167]
          - 'generic "Total rows by date: 5 points, 2023-01-01 → 2023-05-05" [ref=e168]'
        - generic [ref=e173]:
          - generic [ref=e175]:
            - generic "Drag to move" [ref=e176]
            - generic "Sum of id" [ref=e184]
          - generic "18" [ref=e187]
          - 'generic "Sum of id by date: 5 points, 2023-01-01 → 2023-05-05" [ref=e188]'
        - generic [ref=e193]:
          - generic [ref=e195]:
            - generic "Drag to move" [ref=e196]
            - generic "Average of id" [ref=e204]
          - generic "3" [ref=e207]
          - 'generic "Average of id by date: 5 points, 2023-01-01 → 2023-05-05" [ref=e208]'
        - generic [ref=e213]:
          - generic [ref=e215]:
            - generic "Drag to move" [ref=e216]
            - generic "Sum of age" [ref=e224]
          - generic "120" [ref=e227]
          - 'generic "Sum of age by date: 4 points, 2023-01-01 → 2023-05-05" [ref=e228]'
        - generic [ref=e233]:
          - heading "Sum of id by name" [level=3] [ref=e235]:
            - generic "Drag to move" [ref=e236]
            - button "Rename tile" [ref=e247] [cursor=pointer]
          - group [ref=e256]:
            - generic "Compiled SQL" [ref=e257] [cursor=pointer]
        - generic [ref=e260]:
          - heading "Sum of id by status" [level=3] [ref=e262]:
            - generic "Drag to move" [ref=e263]
            - button "Rename tile" [ref=e274] [cursor=pointer]
          - group [ref=e283]:
            - generic "Compiled SQL" [ref=e284] [cursor=pointer]
        - generic [ref=e287]:
          - heading "Count of rows" [level=3] [ref=e289]:
            - generic "Drag to move" [ref=e290]
            - button "Rename tile" [ref=e301] [cursor=pointer]
          - paragraph [ref=e311]: Choose a field for the X axis.
        - generic [ref=e314]:
          - generic [ref=e316]:
            - generic "Drag to move" [ref=e317]
            - generic "Total rows" [ref=e325]
          - generic "6" [ref=e328]
          - 'generic "Total rows by date: 5 points, 2023-01-01 → 2023-05-05" [ref=e329]'
      - generic [ref=e333]:
        - button "Add KPI" [active] [ref=e334] [cursor=pointer]
        - button "Add chart" [ref=e336] [cursor=pointer]
  - complementary "Tile settings" [ref=e338]:
    - generic [ref=e339]:
      - heading "Chart Settings" [level=3] [ref=e340]
      - button "Close" [ref=e341] [cursor=pointer]
```