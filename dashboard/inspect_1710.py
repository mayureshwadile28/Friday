import sys
sys.stdout.reconfigure(encoding='utf-8')

with open('dashboard/templates/dashboard.html', 'r', encoding='utf-8') as f:
    lines = f.readlines()

for idx in range(1710, 1740):
    if idx < len(lines):
        print(f"{idx+1:4d}: {lines[idx].rstrip()}")
