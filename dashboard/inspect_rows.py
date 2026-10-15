import sys
sys.stdout.reconfigure(encoding='utf-8')

with open('dashboard/templates/dashboard.html', 'r', encoding='utf-8') as f:
    lines = f.readlines()

# Let's inspect rows around line 330-360
for idx in range(330, 365):
    print(f"{idx+1:4d}: {lines[idx].rstrip()}")
