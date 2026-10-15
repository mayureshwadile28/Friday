import sys
sys.stdout.reconfigure(encoding='utf-8')

with open('dashboard/templates/dashboard.html', 'r', encoding='utf-8') as f:
    lines = f.readlines()

depth = 0
sections = ['antinukeSection', 'levelingSection', 'antiabuseSection', 'privacySection', 'reactionRolesSection', 'announcementsSection', 'ticketsSection', 'responsesSection', 'automationsSection']

for i, line in enumerate(lines):
    # count <div and </div
    opens = line.count('<div ') + line.count('<div>')
    closes = line.count('</div>')
    for s in sections:
        if f'id="{s}"' in line or f"id='{s}'" in line:
            print(f"Line {i+1}: Start of {s} (depth before = {depth})")
    depth += opens - closes

print(f"Final depth at EOF: {depth}")
