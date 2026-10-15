import sys
sys.stdout.reconfigure(encoding='utf-8')

with open('dashboard/templates/dashboard.html', 'r', encoding='utf-8') as f:
    html = f.read()

import re
instant_blocks = re.findall(r'<div class="sec-name"><span>[^<]+</span>\s*([^<]+)</div>.*?<select class="sec-select" id="([^"]+)">', html, re.DOTALL)
for name, sel_id in instant_blocks:
    # check options
    pos = html.find(f'id="{sel_id}"')
    end_sel = html.find('</select>', pos)
    options = html[pos:end_sel]
    has_timeout = 'value="timeout"' in options
    # check tm_wrap
    wrap_id = sel_id.replace('_pun', '_tm_wrap')
    has_wrap = f'id="{wrap_id}"' in html
    print(f"{name.strip()} ({sel_id}): has_timeout_opt={has_timeout}, has_tm_wrap={has_wrap}")
