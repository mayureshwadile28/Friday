import sys, re
sys.stdout.reconfigure(encoding='utf-8')

with open('dashboard/templates/dashboard.html', 'r', encoding='utf-8') as f:
    html = f.read()

for i, line in enumerate(html.splitlines()):
    if 'Save Security Matrix' in line or 'saveLimits' in line or 'topSaveSecurityBtn' in line:
        print(f"Line {i+1}: {line.strip()}")
