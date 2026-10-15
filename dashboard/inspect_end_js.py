import sys
sys.stdout.reconfigure(encoding='utf-8')

with open('dashboard/static/script.js', 'r', encoding='utf-8') as f:
    lines = f.readlines()

print(f"Total lines in script.js: {len(lines)}")
for idx in range(max(0, len(lines)-150), len(lines)):
    print(f"{idx+1:4d}: {lines[idx].rstrip()[:100]}")
