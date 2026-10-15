import sys, re
sys.stdout.reconfigure(encoding='utf-8')

with open('dashboard/templates/dashboard.html', 'r', encoding='utf-8') as f:
    html = f.read()

token_pattern = re.compile(r'(<!--.*?-->|<div[^>]*>|</div>|<main[^>]*>|</main>|<aside[^>]*>|</aside>)', re.DOTALL)
tokens = token_pattern.findall(html)

stack = []
for idx, token in enumerate(tokens):
    if token.startswith('<!--'):
        continue
    if token.startswith('</'):
        tag = token[2:-1].strip()
        stack.pop()
    else:
        tag = token[1:].split()[0].replace('>', '').strip()
        stack.append((tag, token))
        if 'id=' in token and 'Section' in token:
            print(f"Tag with id: {token[:60]}")
            print(f"  Current stack depth: {len(stack)}")
            print("  Stack ancestry:")
            for s_tag, s_tok in stack[:-1]:
                print(f"    - {s_tok[:60]}")
            print()
