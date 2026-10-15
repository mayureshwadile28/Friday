import sys
sys.stdout.reconfigure(encoding='utf-8')

with open('dashboard/templates/dashboard.html', 'r', encoding='utf-8') as f:
    lines = f.readlines()

for i in range(175, 235):
    if i < len(lines):
        print(f"{i+1}: {lines[i]}", end="")
