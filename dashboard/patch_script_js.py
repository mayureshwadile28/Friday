import sys, re
sys.stdout.reconfigure(encoding='utf-8')

js_path = 'dashboard/static/script.js'
with open(js_path, 'r', encoding='utf-8') as f:
    js = f.read()

# 1. Update loadDataForActiveTab to be async and call loadCustomResponsesSettings
old_tab_loader = """function loadDataForActiveTab() {
    const activeTab = document.querySelector('.nav-item.active').dataset.tab;
    if (activeTab === 'antinukeSection') await loadAntinukeSettings();
    else if (activeTab === 'levelingSection') await loadLevelingSettings();
    else if (activeTab === 'antiabuseSection') await loadAntiabuseSettings();
    else if (activeTab === 'privacySection') await loadPrivacySettings();
    else if (activeTab === 'reactionRolesSection') await loadReactionRolesSettings();
    else if (activeTab === 'announcementsSection') await loadAnnouncementsSettings();
    else if (activeTab === 'ticketsSection') await loadTicketsSettings();
    else if (activeTab === 'responsesSection') await loadResponsesSettings();
}"""

new_tab_loader = """async function loadDataForActiveTab() {
    const activeTabEl = document.querySelector('.nav-item.active');
    if (!activeTabEl) return;
    const activeTab = activeTabEl.dataset.tab;
    if (activeTab === 'antinukeSection') await loadAntinukeSettings();
    else if (activeTab === 'levelingSection') await loadLevelingSettings();
    else if (activeTab === 'antiabuseSection') await loadAntiabuseSettings();
    else if (activeTab === 'privacySection') await loadPrivacySettings();
    else if (activeTab === 'reactionRolesSection') await loadReactionRolesSettings();
    else if (activeTab === 'announcementsSection') await loadAnnouncementsSettings();
    else if (activeTab === 'ticketsSection') await loadTicketsSettings();
    else if (activeTab === 'responsesSection') await loadCustomResponsesSettings();
}"""

if old_tab_loader in js:
    js = js.replace(old_tab_loader, new_tab_loader, 1)
    print("Fixed loadDataForActiveTab!")

# 2. Fix the initial event listeners in setupEventListeners
# Replace document.getElementById('saveLimitsBtn').addEventListener('click', saveLimits);
# with safe check
old_sec_listeners = """    // Anti-Nuke Handlers
    document.getElementById('antinukeToggle').addEventListener('change', toggleAntinuke);
    document.getElementById('saveLimitsBtn').addEventListener('click', saveLimits);
    const topSaveBtn = document.getElementById('topSaveSecurityBtn');
    if (topSaveBtn) {
        topSaveBtn.addEventListener('click', saveLimits);
    }
    document.getElementById('whitelistAddBtn').addEventListener('click', () => addWhitelistUser('antinuke'));"""

new_sec_listeners = """    // Anti-Nuke Handlers
    const antinukeTgl = document.getElementById('antinukeToggle');
    if (antinukeTgl) antinukeTgl.addEventListener('change', toggleAntinuke);
    
    const saveLimitsBtn = document.getElementById('saveLimitsBtn');
    if (saveLimitsBtn) saveLimitsBtn.addEventListener('click', saveLimits);
    
    const topSaveBtn = document.getElementById('topSaveSecurityBtn');
    if (topSaveBtn) {
        topSaveBtn.addEventListener('click', saveLimits);
    }
    
    const wlAddBtn = document.getElementById('whitelistAddBtn');
    if (wlAddBtn) wlAddBtn.addEventListener('click', () => addWhitelistUser('antinuke'));"""

if old_sec_listeners in js:
    js = js.replace(old_sec_listeners, new_sec_listeners, 1)
    print("Fixed Anti-Nuke listener attachments!")

# Also fix saveLevelingBtn, abuseWhitelistAddBtn, privacyIgnoreAddBtn
js = js.replace("document.getElementById('saveLevelingBtn').addEventListener('click', saveLeveling);",
                "const slBtn = document.getElementById('saveLevelingBtn'); if (slBtn) slBtn.addEventListener('click', saveLeveling);")

js = js.replace("document.getElementById('abuseWhitelistAddBtn').addEventListener('click', () => addWhitelistUser('abuse'));",
                "const awBtn = document.getElementById('abuseWhitelistAddBtn'); if (awBtn) awBtn.addEventListener('click', () => addWhitelistUser('abuse'));")

js = js.replace("document.getElementById('privacyIgnoreAddBtn').addEventListener('click', addPrivacyIgnored);",
                "const piBtn = document.getElementById('privacyIgnoreAddBtn'); if (piBtn) piBtn.addEventListener('click', addPrivacyIgnored);")

print("Fixed other safe listener attachments!")

# 3. Add Custom Responses variable badges and emoji buttons listeners inside setupEventListeners
cr_init_block = """
    // Custom Responses Event Listeners (Emoji picker & variable inserters)
    document.querySelectorAll('.resp-var-badge').forEach(badge => {
        badge.addEventListener('click', (e) => {
            e.preventDefault();
            const targetId = badge.getAttribute('data-target');
            const varText = badge.getAttribute('data-var') || badge.textContent;
            const input = document.getElementById(targetId);
            if (!input) return;
            const start = input.selectionStart ?? input.value.length;
            const end = input.selectionEnd ?? input.value.length;
            input.value = input.value.substring(0, start) + varText + input.value.substring(end);
            input.focus();
            input.selectionStart = input.selectionEnd = start + varText.length;
        });
    });

    document.querySelectorAll('.resp-emoji-btn').forEach(btn => {
        btn.addEventListener('click', (e) => {
            e.preventDefault();
            const targetId = btn.getAttribute('data-target');
            const input = document.getElementById(targetId);
            if (!input) return;
            openEmojiPicker(btn, (emojiVal) => {
                const start = input.selectionStart ?? input.value.length;
                const end = input.selectionEnd ?? input.value.length;
                input.value = input.value.substring(0, start) + emojiVal + ' ' + input.value.substring(end);
                input.focus();
                input.selectionStart = input.selectionEnd = start + emojiVal.length + 1;
            });
        });
    });

    const saveRespBtn = document.getElementById('saveResponsesBtn') || document.getElementById('saveCustomResponsesBtn');
    if (saveRespBtn) {
        saveRespBtn.addEventListener('click', saveResponsesSettings);
    }
"""

if "document.querySelectorAll('.resp-var-badge')" not in js:
    # insert before end of setupEventListeners
    js = js.replace("document.getElementById('saveLimitsBtn')", cr_init_block + "\n    document.getElementById('saveLimitsBtn')", 1)
    print("Injected custom responses listeners!")

with open(js_path, 'w', encoding='utf-8') as f:
    f.write(js)

print("script.js updated successfully!")
