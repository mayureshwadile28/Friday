import sys, re
sys.stdout.reconfigure(encoding='utf-8')

with open('dashboard/static/script.js', 'r', encoding='utf-8') as f:
    js = f.read()

for i, line in enumerate(js.splitlines()):
    if 'resp-emoji-btn' in line or 'openCrEmojiPicker' in line or 'data-target' in line:
        print(f"Line {i+1}: {line.strip()[:100]}")
