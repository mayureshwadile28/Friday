import sys
sys.stdout.reconfigure(encoding='utf-8')

with open('dashboard/templates/dashboard.html', 'r', encoding='utf-8') as f:
    lines = f.readlines()

sections = [
    ('antinukeSection', 179),
    ('levelingSection', 780),
    ('antiabuseSection', 911),
    ('privacySection', 939),
    ('reactionRolesSection', 1058),
    ('announcementsSection', 1195),
    ('ticketsSection', 1384),
    ('responsesSection', 1726)
]

# Let's see where each section starts and ends, assuming hero-toggle-card is closed
# Let's inspect the closing tags of each section
for idx, (name, start_line) in enumerate(sections):
    end_line = sections[idx+1][1] if idx+1 < len(sections) else len(lines)
    section_lines = lines[start_line-1:end_line-1]
    opens = sum(l.count('<div ') + l.count('<div>') for l in section_lines)
    closes = sum(l.count('</div>') for l in section_lines)
    print(f"Section {name} (lines {start_line}..{end_line}): opens={opens}, closes={closes}, net={opens-closes}")
