import sys, re
sys.stdout.reconfigure(encoding='utf-8')

with open('dashboard/app.py', 'r', encoding='utf-8') as f:
    app = f.read()

m = re.search(r'@app\.route\([\'"][^\'"]*respons[^\'"]*[\'"].*?return', app, re.DOTALL)
if m:
    print(m.group(0)[:1200])

for m in re.finditer(r'@app\.(?:route|post|get)\([\'"][^\'"]*respons[^\'"]*[\'"].*?(?=@app|\Z)', app, re.DOTALL):
    print("ROUTE:")
    print(m.group(0)[:800])
    print("="*40)
