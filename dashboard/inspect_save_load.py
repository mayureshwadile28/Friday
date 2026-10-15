import sys, re
sys.stdout.reconfigure(encoding='utf-8')

with open('dashboard/static/script.js', 'r', encoding='utf-8') as f:
    js = f.read()

m = re.search(r'function saveLimits.*?function loadAntinukeSettings', js, re.DOTALL)
if m:
    print("saveLimits:")
    print(m.group(0)[:1200])

m2 = re.search(r'function loadAntinukeSettings.*?\Z', js, re.DOTALL)
if m2:
    print("\nloadAntinukeSettings:")
    print(m2.group(0)[:1200])
