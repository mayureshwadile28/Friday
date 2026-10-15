import sys, re
sys.stdout.reconfigure(encoding='utf-8')

with open('dashboard/templates/dashboard.html', 'r', encoding='utf-8') as f:
    lines = f.readlines()

def inspect_range(start_name, start_idx, end_idx):
    print(f"=== {start_name} (lines {start_idx}..{end_idx}) ===")
    depth = 0
    for i in range(start_idx-1, end_idx):
        line = lines[i]
        opens = line.count('<div ') + line.count('<div>')
        closes = line.count('</div>')
        depth += opens - closes
        if opens != closes or 'Section' in line:
            # print significant lines
            print(f"{i+1:4d} (depth {depth:+2d}): {line.rstrip()[:90]}")
    print(f"Final net depth for {start_name}: {depth}\n")

inspect_range("announcementsSection", 1195, 1384)
inspect_range("ticketsSection", 1384, 1726)
inspect_range("responsesSection", 1726, 2030)
