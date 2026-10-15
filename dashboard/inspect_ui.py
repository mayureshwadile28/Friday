import re

with open('dashboard/static/script.js', 'r', encoding='utf-8') as f:
    js = f.read()

with open('dashboard/templates/dashboard.html', 'r', encoding='utf-8') as f:
    html = f.read()

m = re.search(r'function setupEventListeners.*?function loadGuilds', js, re.DOTALL)
if m:
    event_listener_block = m.group(0)
    # find all getElementById calls
    ids = re.findall(r"document\.getElementById\(['\"]([^'\"]+)['\"]\)\.addEventListener", event_listener_block)
    print("Found addEventListener IDs:", len(ids))
    for i in ids:
        found = (f'id="{i}"' in html) or (f"id='{i}'" in html)
        print(f"  {i}: {found}")
