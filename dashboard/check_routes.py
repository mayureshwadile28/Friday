import sys, re
sys.stdout.reconfigure(encoding='utf-8')

with open('dashboard/app.py', 'r', encoding='utf-8') as f:
    app = f.read()

routes = re.findall(r"@app\.(?:route|post|get)\(['\"]([^'\"]+)['\"]", app)
print("All routes in app.py:")
for r in routes:
    if 'respons' in r:
        print("  -", r)
