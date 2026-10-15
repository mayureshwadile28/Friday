import sys
sys.stdout.reconfigure(encoding='utf-8')

with open('dashboard/templates/dashboard.html', 'r', encoding='utf-8') as f:
    html = f.read()

# Let's extract antinukeSection
start = html.find('id="antinukeSection"')
end = html.find('id="levelingSection"')
antinuke_html = html[start:end]

# Find all cards, grids, containers in antinukeSection
import re
divs = re.findall(r'<div class="([^"]+)"', antinuke_html)
print("Div classes in antinukeSection:")
for d in set(divs):
    print(" -", d)

# Let's check if there are 2-column or unbalanced grids
for line in antinuke_html.splitlines():
    if 'grid' in line.lower() or 'column' in line.lower() or 'flex' in line.lower() or 'col' in line.lower():
        print(line[:120])
