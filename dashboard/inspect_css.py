import sys
sys.stdout.reconfigure(encoding='utf-8')

with open('dashboard/static/style.css', 'r', encoding='utf-8') as f:
    css = f.read()

import re
rules = re.findall(r'(\.sec-[^{]+|\.hero-[^{]+)\{([^}]+)\}', css)
for sel, body in rules:
    print(sel.strip(), "=>", body.strip().replace('\n', ' '))
