import sys, re
sys.stdout.reconfigure(encoding='utf-8')

with open('dashboard/templates/dashboard.html', 'r', encoding='utf-8') as f:
    html = f.read()

# Let's write a simple HTML tag parser
token_pattern = re.compile(r'(<!--.*?-->|<div[^>]*>|</div>|<main[^>]*>|</main>|<aside[^>]*>|</aside>)', re.DOTALL)
tokens = token_pattern.findall(html)

stack = []
for idx, token in enumerate(tokens):
    if token.startswith('<!--'):
        continue
    if token.startswith('</'):
        tag = token[2:-1].strip()
        if not stack:
            print(f"Error: Closing {tag} but stack is empty at token #{idx}")
        else:
            prev_tag, prev_token = stack.pop()
            if prev_tag != tag:
                print(f"Mismatch: closed {tag} but top was {prev_tag} ({prev_token[:40]})")
    else:
        # open tag
        tag = token[1:].split()[0].replace('>', '').strip()
        stack.append((tag, token))

print("Remaining unclosed tags at EOF:", len(stack))
for t, tok in stack:
    print(f"  Unclosed: {t} -> {tok[:60]}")
