import sys, re
sys.stdout.reconfigure(encoding='utf-8')

with open('dashboard/static/script.js', 'r', encoding='utf-8') as f:
    js = f.read()

# Find all occurrences of document.getElementById(...).addEventListener
unsafe_listeners = re.findall(r'document\.getElementById\([\'"]([^\'"]+)[\'"]\)\.addEventListener', js)
print("Unsafe addEventListener calls on getElementById:")
for i in unsafe_listeners:
    print(" -", i)
