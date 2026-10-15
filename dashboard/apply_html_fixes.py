import sys, re
sys.stdout.reconfigure(encoding='utf-8')

html_path = 'dashboard/templates/dashboard.html'
with open(html_path, 'r', encoding='utf-8') as f:
    html = f.read()

# 1. Fix hero-toggle-card in Anti-Nuke
old_hero = """<div class="hero-toggle-card">
<div class="hero-toggle-left">
<div class="hero-toggle-icon">
<svg fill="none" height="28" stroke="currentColor" stroke-width="2" viewbox="0 0 24 24" width="28">
<path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z"></path>
</svg>
</div>
<div>
<div class="hero-toggle-title">
<span>Master Anti-Nuke Engine</span>
<span class="status-pill active" id="antinukeStatusBadge">
<span class="status-pulse"></span> Active Protection
                                </span>
</div>
<div class="hero-toggle-desc">Master switch controlling all automated punishments across destructive thresholds, instant actions, and detection rules.</div>
</div>
</div>
<!-- Master Anti-Nuke Paused Banner -->"""

new_hero = """<div class="hero-toggle-card">
<div class="hero-toggle-left">
<div class="hero-toggle-icon">
<svg fill="none" height="28" stroke="currentColor" stroke-width="2" viewbox="0 0 24 24" width="28">
<path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z"></path>
</svg>
</div>
<div>
<div class="hero-toggle-title">
<span>Master Anti-Nuke Engine</span>
<span class="status-pill active" id="antinukeStatusBadge">
<span class="status-pulse"></span> Active Protection
                                </span>
</div>
<div class="hero-toggle-desc">Master switch controlling all automated punishments across destructive thresholds, instant actions, and detection rules.</div>
</div>
</div>
<label class="switch">
<input checked="" id="antinukeToggle" type="checkbox"/>
<span class="slider"></span>
</label>
</div>
<!-- Master Anti-Nuke Paused Banner -->"""

if old_hero in html:
    html = html.replace(old_hero, new_hero, 1)
    print("Fixed hero-toggle-card!")
else:
    print("WARNING: old_hero pattern not found!")

# 2. Fix all Tailwind tm_wrap blocks to use sleek .sec-tm-wrap
tailwind_tm_pattern = re.compile(
    r'<div class="hidden mt-2 flex items-center bg-slate-800/50 rounded-lg p-2 border border-slate-700/50" id="([^"]+)" style="display: none;">\s*'
    r'<i class="w-4 h-4 text-slate-400 mr-2" data-lucide="clock"></i>\s*'
    r'<input class="bg-transparent text-sm text-slate-300 outline-none w-full" id="([^"]+)" max="40320" min="1" placeholder="[^"]*" type="number"/>\s*'
    r'<span class="text-xs text-slate-500 ml-2">min</span>\s*'
    r'</div>',
    re.DOTALL
)

def replace_tm(match):
    wrap_id = match.group(1)
    input_id = match.group(2)
    return f'''<div class="sec-tm-wrap" id="{wrap_id}" style="display: none;">
<span style="font-size: 11px;">⏱️</span>
<input class="sec-input sec-tm-input" id="{input_id}" max="40320" min="1" placeholder="mins" type="number" value="10"/>
<span class="sec-tm-unit">mins</span>
</div>'''

html, tm_repl_count = tailwind_tm_pattern.subn(replace_tm, html)
print(f"Replaced {tm_repl_count} Tailwind TM wrappers with clean .sec-tm-wrap!")

# Remove duplicate raid_tm_wrap if present
html = html.replace('''<div class="sec-tm-wrap" id="sec_raid_tm_wrap" style="display: none;">
<span>TM:</span>
<input class="sec-input sec-tm-input" id="raidTmInput" min="1" type="number" value="10"/>
<span class="sec-tm-unit">mins</span>
</div>''', '')

# Remove duplicate spam_tm_wrap if present
html = html.replace('''<div class="sec-tm-wrap" id="sec_spam_tm_wrap" style="display: flex;">
<span>TM:</span>
<input class="sec-input sec-tm-input" id="spamTmInput" min="1" type="number" value="2"/>
<span class="sec-tm-unit">mins</span>
</div>''', '')

# 3. Remove duplicate save button at bottom of matrix (keep only the clean status pill or right align)
old_dup_save = """<button class="btn btn-primary" id="saveLimitsBtn">
<svg fill="none" height="14" stroke="currentColor" stroke-width="2" viewbox="0 0 24 24" width="14"><path d="M19 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h11l5 5v11a2 2 0 0 1-2 2z"></path><polyline points="17 21 17 13 7 13 7 21"></polyline><polyline points="7 3 7 8 15 8"></polyline></svg>
                                Save Security Matrix
                            </button>"""
if old_dup_save in html:
    html = html.replace(old_dup_save, "")
    print("Removed duplicate Save Security Matrix button at bottom!")

# 4. Fix announcementsSection extra </div>
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

if old_ann in html:
    html = html.replace(old_ann, new_ann, 1)
    print("Fixed announcementsSection extra closing div!")
else:
    print("WARNING: old_ann pattern not found!")

# 5. Fix ticketsSection closing before responsesSection
old_resp_start = """<!-- ──────────────── MODULE 8: CUSTOM RESPONSES ──────────────── -->
<div class="section tab-content" id="responsesSection" style="display: none;">"""

new_resp_start = """</div> <!-- End #ticketsSection -->
<!-- ──────────────── MODULE 8: CUSTOM RESPONSES ──────────────── -->
<div class="section tab-content" id="responsesSection" style="display: none;">"""

if old_resp_start in html:
    html = html.replace(old_resp_start, new_resp_start, 1)
    print("Added closing div for ticketsSection!")
else:
    print("WARNING: old_resp_start not found!")

# 6. Fix EOF closing tags
old_eof = """</div>
</div>
</div></main>"""

new_eof = """</div>
</div></main>"""

if old_eof in html:
    html = html.replace(old_eof, new_eof, 1)
    print("Fixed EOF closing divs!")
else:
    print("WARNING: old_eof not found!")

# Also ensure responsesSection save button has id="saveCustomResponsesBtn" or both
html = html.replace('id="saveResponsesBtn"', 'id="saveResponsesBtn" data-alias="saveCustomResponsesBtn"')

with open(html_path, 'w', encoding='utf-8') as f:
    f.write(html)

print("dashboard.html updated successfully!")
