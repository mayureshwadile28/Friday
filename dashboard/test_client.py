import urllib.request
import json
import sys

sys.stdout.reconfigure(encoding='utf-8')

# Test main page
req = urllib.request.urlopen('http://localhost:5000/')
html = req.read().decode('utf-8')
print("Status:", req.status)
print("Page length:", len(html))

# Verify all key elements in HTML
checks = [
    ('antinukeToggle', 'id="antinukeToggle"'),
    ('topSaveSecurityBtn', 'id="topSaveSecurityBtn"'),
    ('hero-toggle-card closed', '<div class="hero-toggle-card">'),
    ('masterPausedBanner', 'id="masterPausedBanner"'),
    ('secProtectedControls', 'id="secProtectedControls"'),
    ('antiRaidToggle', 'id="antiRaidToggle"'),
    ('antiSpamToggle', 'id="antiSpamToggle"'),
    ('sec_lim_ban_tm_wrap', 'id="sec_lim_ban_tm_wrap"'),
    ('levelingSection', 'id="levelingSection"'),
    ('antiabuseSection', 'id="antiabuseSection"'),
    ('privacySection', 'id="privacySection"'),
    ('reactionRolesSection', 'id="reactionRolesSection"'),
    ('announcementsSection', 'id="announcementsSection"'),
    ('ticketsSection', 'id="ticketsSection"'),
    ('responsesSection', 'id="responsesSection"'),
    ('resp_ban_success', 'id="resp_ban_success"')
]

for name, needle in checks:
    print(f"  {name}: {'PASS' if needle in html else 'FAIL'}")

# Test API endpoints
try:
    guilds_req = urllib.request.urlopen('http://localhost:5000/api/guilds')
    guilds = json.loads(guilds_req.read().decode('utf-8'))
    print("\nAPI /api/guilds:", guilds)
    if guilds:
        gid = guilds[0]['id']
        print(f"Testing guild {gid} endpoints:")
        sec_req = urllib.request.urlopen(f'http://localhost:5000/api/guild/{gid}/security')
        sec_data = json.loads(sec_req.read().decode('utf-8'))
        print("  /security success:", sec_data.get('success'), "antinuke_active:", sec_data.get('antinuke_active'))
        
        resp_req = urllib.request.urlopen(f'http://localhost:5000/api/guild/{gid}/custom_responses')
        resp_data = json.loads(resp_req.read().decode('utf-8'))
        print("  /custom_responses keys:", len(resp_data))
except Exception as e:
    print("API Error:", e)
