import sys, re
sys.stdout.reconfigure(encoding='utf-8')

with open('dashboard/templates/dashboard.html', 'r', encoding='utf-8') as f:
    html = f.read()

start = html.find('id="responsesSection"')
end = html.find('</main>')
resp_html = html[start:end]

cards = re.findall(r'<div class="resp-card-title">(.*?)</div>', resp_html)
print(f"Cards in responsesSection ({len(cards)}):")
for c in cards:
    print(" -", c)

fields = re.findall(r'<input [^>]*id="([^"]+)"', resp_html)
print(f"\nTotal inputs in responsesSection: {len(fields)}")
for fid in fields:
    print("  *", fid)
