import csv
import random

headers = ['mixed_col', 'ambiguous_date', 'mostly_null', 'category'] + [f'col_{i}' for i in range(1, 43)]

rows = []
for i in range(100):
    row = {}
    
    # Mixed type: mostly ints, some string garbage
    if i % 10 == 0:
        row['mixed_col'] = "UNKNOWN"
    elif i % 15 == 0:
        row['mixed_col'] = "N/A"
    else:
        row['mixed_col'] = str(random.randint(100, 999))
        
    # Ambiguous date: 03/04/2025
    row['ambiguous_date'] = f"{random.randint(1,12):02d}/{random.randint(1,12):02d}/2025"
    
    # >90% null
    if random.random() < 0.95:
        row['mostly_null'] = ""
    else:
        row['mostly_null'] = "RARE_VALUE"
        
    # Low cardinality
    row['category'] = random.choice(['Red', 'Green', 'Blue'])
    
    # Fill remaining 42 columns
    for j in range(1, 43):
        if j % 2 == 0:
            row[f'col_{j}'] = str(random.uniform(0, 100))
        else:
            row[f'col_{j}'] = f"str_val_{j}"
            
    rows.append(row)

with open('messy.csv', 'w', newline='', encoding='utf-8') as f:
    writer = csv.DictWriter(f, fieldnames=headers)
    writer.writeheader()
    writer.writerows(rows)
