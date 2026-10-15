import sys, re
sys.stdout.reconfigure(encoding='utf-8')

with open('dashboard/templates/dashboard.html', 'r', encoding='utf-8') as f:
    lines = f.readlines()

stack = []
for i in range(1194, 1383):
    line = lines[i]
    tokens = re.findall(r'(<div[^>]*>|</div>)', line)
    for t in tokens:
        if t.startswith('</'):
            if stack:
                stack.pop()
            else:
                print(f"Extra close at line {i+1}")
        else:
            tag_class = re.search(r'class="([^"]+)"', t)
            tag_id = re.search(r'id="([^"]+)"', t)
            name = (tag_id.group(1) if tag_id else (tag_class.group(1) if tag_class else 'div'))
            stack.append((i+1, name))

print("Unclosed in announcementsSection:")
for lnum, name in stack:
    print(f"  Line {lnum}: {name}")
