import sys, re
sys.stdout.reconfigure(encoding='utf-8')

with open('dashboard/templates/dashboard.html', 'r', encoding='utf-8') as f:
    html = f.read()

# Fix 1: Add switch and close hero-toggle-card
old_hero = """<div class="hero-toggle-desc">Master switch controlling all automated punishments across destructive thresholds, instant actions, and detection rules.</div>
</div>
</div>
<!-- Master Anti-Nuke Paused Banner -->"""

new_hero = """<div class="hero-toggle-desc">Master switch controlling all automated punishments across destructive thresholds, instant actions, and detection rules.</div>
</div>
</div>
<label class="switch">
<input checked="" id="antinukeToggle" type="checkbox"/>
<span class="slider"></span>
</label>
</div>
<!-- Master Anti-Nuke Paused Banner -->"""

assert old_hero in html, "old_hero not found!"
html2 = html.replace(old_hero, new_hero, 1)

# Fix 2: Remove extra </div> at line 1382
old_ann = """<span id="annSimFooterText">Friday Broadcast System • Official Notification</span>
</div>
</div>
</div>
</div>
</div>
</div>
</div>
</div>
</div>
</div>
<!-- ======================= TICKETS SECTION ======================= -->"""

# Count closing divs in old_ann: there are 10 </div>
# Replace with 9 </div>
new_ann = """<span id="annSimFooterText">Friday Broadcast System • Official Notification</span>
</div>
</div>
</div>
</div>
</div>
</div>
</div>
</div>
</div>
<!-- ======================= TICKETS SECTION ======================= -->"""

assert old_ann in html2, "old_ann not found!"
html3 = html2.replace(old_ann, new_ann, 1)

# Fix 3: Close ticketsSection before responsesSection
old_resp_start = """<!-- ──────────────── MODULE 8: CUSTOM RESPONSES ──────────────── -->
<div class="section tab-content" id="responsesSection" style="display: none;">"""

new_resp_start = """</div> <!-- End #ticketsSection -->
<!-- ──────────────── MODULE 8: CUSTOM RESPONSES ──────────────── -->
<div class="section tab-content" id="responsesSection" style="display: none;">"""

assert old_resp_start in html3, "old_resp_start not found!"
html4 = html3.replace(old_resp_start, new_resp_start, 1)

# Fix 4: Fix EOF closing tags
old_eof = """</div>
</div>
</div>
</div></main>"""

# At end of responsesSection, we had:
# line 2026: </div> (closes resp-card)
# line 2027: </div> (closes responsesSection)
# line 2028: </div> (closes main-container)
# line 2029: </div></main> (extra div)
old_eof_block = """</div>
</div>
</div></main>"""

assert old_eof_block in html4, "old_eof_block not found!"
html5 = html4.replace(old_eof_block, """</div>
</div></main>""", 1)

print("All replacements matched! Now checking ancestry stack...")

token_pattern = re.compile(r'(<!--.*?-->|<div[^>]*>|</div>|<main[^>]*>|</main>|<aside[^>]*>|</aside>)', re.DOTALL)
tokens = token_pattern.findall(html5)

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
            print(f"Section tag: {token[:60]}")
            print(f"  Current stack depth: {len(stack)}")
            print("  Stack ancestry:")
            for s_tag, s_tok in stack[:-1]:
                print(f"    - {s_tok[:60]}")
            print()

print(f"Final stack size at EOF: {len(stack)}")
for t, tok in stack:
    print(f"  Remaining: {t} -> {tok[:60]}")
