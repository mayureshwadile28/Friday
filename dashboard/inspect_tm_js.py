import sys, re
sys.stdout.reconfigure(encoding='utf-8')

with open('dashboard/static/script.js', 'r', encoding='utf-8') as f:
    js = f.read()

# Let's search for tm_wrap
matches = re.findall(r'[a-zA-Z0-9_]*tm_wrap[a-zA-Z0-9_]*', js)
print("Unique tm_wrap in script.js:", set(matches))

# Let's see the punishment select change handler
m = re.search(r'// Wire all 21 punishment select.*?function', js, re.DOTALL)
if m:
    print("\nHandler code:")
    print(m.group(0)[:1500])
