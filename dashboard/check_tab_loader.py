import sys, re
sys.stdout.reconfigure(encoding='utf-8')

with open('dashboard/static/script.js', 'r', encoding='utf-8') as f:
    js = f.read()

m = re.search(r'function loadDataForActiveTab.*?function', js, re.DOTALL)
if m:
    print(m.group(0))
