with open('dashboard/templates/dashboard.html', 'r', encoding='utf-8') as f:
    lines = f.readlines()

for idx in range(178, 230):
    print(f"{idx+1:4d}: {lines[idx].rstrip()}")
