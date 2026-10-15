import sys, re
sys.stdout.reconfigure(encoding='utf-8')

with open('dashboard/static/script.js', 'r', encoding='utf-8') as f:
    js = f.read()

m = re.search(r'async function loadCustomResponsesSettings.*?async function saveResponsesSettings.*?\n\}', js, re.DOTALL)
if m:
    print(m.group(0))
else:
    print("Pattern not found, searching individually...")
    for fn in ['loadCustomResponsesSettings', 'saveResponsesSettings']:
        m = re.search(rf'async function {fn}.*?\n\}}', js, re.DOTALL)
        if m:
            print(f"=== {fn} ===")
            print(m.group(0)[:800])
