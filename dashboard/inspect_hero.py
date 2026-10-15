import sys
sys.stdout.reconfigure(encoding='utf-8')

with open('dashboard/templates/dashboard.html', 'r', encoding='utf-8') as f:
    lines = f.readlines()

print("".join(lines[178:225]))
