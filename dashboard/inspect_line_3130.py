import sys
sys.stdout.reconfigure(encoding='utf-8')

with open('dashboard/static/script.js', 'r', encoding='utf-8') as f:
    lines = f.readlines()

for idx in range(3115, min(3150, len(lines))):
    print(f"{idx+1:4d}: {lines[idx].rstrip()}")
