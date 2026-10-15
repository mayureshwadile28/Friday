import sys, re
sys.stdout.reconfigure(encoding='utf-8')

with open('dashboard/templates/dashboard.html', 'r', encoding='utf-8') as f:
    html = f.read()

start = html.find('id="antinukeSection"')
end = html.find('id="levelingSection"')
sec_html = html[start:end]

ids = re.findall(r'id=["\']([^"\']+)["\']', sec_html)
print(f"Total IDs in antinukeSection: {len(ids)}")
print(sorted(set(ids)))
