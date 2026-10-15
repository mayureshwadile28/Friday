import sys, re
sys.stdout.reconfigure(encoding='utf-8')

js_path = 'dashboard/static/script.js'
with open(js_path, 'r', encoding='utf-8') as f:
    js = f.read()

# Replace loadCustomResponsesSettings & saveResponsesSettings
old_cr_block_pattern = re.compile(r'async function loadCustomResponsesSettings.*?async function saveResponsesSettings.*?finally\s*\{[^}]+\}\s*\}', re.DOTALL)

new_cr_block = """async function loadCustomResponsesSettings() {
    if (!currentGuildId) return;
    try {
        const resp = await fetch(`/api/guild/${currentGuildId}/custom_responses`);
        const data = await resp.json();
        const conf = data.config || data || {};
        CUSTOM_RESPONSES_SCHEMA.forEach(cr => {
            const input = document.getElementById(`resp_${cr.id}`) || document.getElementById(`cr_${cr.id}`);
            if (input) {
                input.value = conf[cr.id] !== undefined ? conf[cr.id] : (conf[`resp_${cr.id}`] || '');
            }
        });
    } catch (e) {
        console.error("Failed to load custom responses", e);
    }
}

async function saveResponsesSettings() {
    if (!currentGuildId) return showToast('⚠️ Select a server first!');
    const saveBtn = document.getElementById('saveResponsesBtn') || document.getElementById('saveCustomResponsesBtn');
    const origHtml = saveBtn ? saveBtn.innerHTML : '';
    if (saveBtn) {
        saveBtn.disabled = true;
        saveBtn.innerHTML = `<span>⏳</span> Saving...`;
    }
    
    const payload = {};
    CUSTOM_RESPONSES_SCHEMA.forEach(cr => {
        const input = document.getElementById(`resp_${cr.id}`) || document.getElementById(`cr_${cr.id}`);
        if (input) {
            payload[cr.id] = input.value.trim();
        }
    });
    
    try {
        const res = await fetch(`/api/guild/${currentGuildId}/custom_responses/update`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(payload)
        });
        const resData = await res.json();
        if (resData.success) {
            showToast('✅ Custom responses saved successfully!');
        } else {
            showToast('❌ Failed to save custom responses');
        }
    } catch (e) {
        showToast('❌ Failed to save custom responses');
    } finally {
        if (saveBtn) {
            saveBtn.disabled = false;
            saveBtn.innerHTML = origHtml;
        }
    }
}"""

if old_cr_block_pattern.search(js):
    js = old_cr_block_pattern.sub(new_cr_block, js)
    print("Replaced loadCustomResponsesSettings and saveResponsesSettings successfully!")
else:
    print("WARNING: old_cr_block_pattern not matched!")

# Now replace saveLimits & loadAntinukeSettings with bulletproof versions
old_limits_pattern = re.compile(r'function saveLimits\(\)\s*\{.*?async function loadAntinukeSettings\(\)\s*\{.*?catch\s*\(e\)\s*\{\s*\}\s*\}', re.DOTALL)

new_limits_block = """function saveLimits() {
    if (!currentGuildId) return showToast('⚠️ Select a server first!');
    const saveBtn = document.getElementById('saveLimitsBtn');
    const topSaveBtn = document.getElementById('topSaveSecurityBtn');
    const origHtml = topSaveBtn ? topSaveBtn.innerHTML : (saveBtn ? saveBtn.innerHTML : '');
    
    if (saveBtn) {
        saveBtn.disabled = true;
        saveBtn.innerHTML = `<span>⏳</span> Saving...`;
    }
    if (topSaveBtn) {
        topSaveBtn.disabled = true;
        topSaveBtn.innerHTML = `<span>⏳</span> Saving...`;
    }

    try {
        const limitsData = {};
        const limitKeys = ['ban', 'kick', 'role_create', 'role_delete', 'channel_create', 'channel_delete', 'mention'];
        limitKeys.forEach(k => {
            const limVal = (document.getElementById(`sec_lim_${k}_val`) || document.getElementById(`sec_lim_${k}`))?.value;
            const punVal = document.getElementById(`sec_lim_${k}_pun`)?.value;
            const tmVal = document.getElementById(`sec_lim_${k}_tm`)?.value;
            const toggleVal = (document.getElementById(`sec_lim_${k}_en`) || document.getElementById(`sec_lim_${k}_tgl`))?.checked;
            limitsData[k] = {
                limit: parseInt(limVal || 3),
                punishment: punVal || 'ban',
                timeout_mins: parseInt(tmVal || 10),
                enabled: toggleVal !== false
            };
        });

        const instantData = {};
        const instantKeys = [
            'bot_add', 'prune', 'dangerous_perms', 'dangerous_role_add',
            'vanity_change', 'server_rename', 'server_icon', 'role_rename',
            'channel_rename', 'emoji_delete', 'emoji_rename', 'invite_delete'
        ];
        instantKeys.forEach(k => {
            const punVal = document.getElementById(`sec_inst_${k}_pun`)?.value;
            const tmVal = document.getElementById(`sec_inst_${k}_tm`)?.value;
            const toggleVal = (document.getElementById(`sec_inst_${k}_en`) || document.getElementById(`sec_inst_${k}_tgl`))?.checked;
            instantData[k] = {
                punishment: punVal || 'kick',
                timeout_mins: parseInt(tmVal || 10),
                enabled: toggleVal !== false
            };
        });

        const detectData = {
            invite_link: {
                enabled: (document.getElementById('sec_det_invite_link_en') || document.getElementById('sec_det_invite_tgl'))?.checked ?? true
            },
            anti_link: {
                enabled: (document.getElementById('sec_det_link_en') || document.getElementById('sec_det_link_tgl'))?.checked ?? true
            },
            ghost_ping: {
                enabled: (document.getElementById('sec_det_ghost_ping_en') || document.getElementById('sec_det_ghost_tgl'))?.checked ?? true
            }
        };

        const antiraidData = {
            enabled: document.getElementById('antiRaidToggle')?.checked ?? true,
            join_threshold: parseInt((document.getElementById('secRaidThreshold') || document.getElementById('secRaidLimit'))?.value || 5),
            time_window: 10,
            action: document.getElementById('secRaidAction')?.value || 'kick',
            timeout_mins: parseInt(document.getElementById('sec_raid_tm')?.value || 10)
        };

        const antispamData = {
            enabled: document.getElementById('antiSpamToggle')?.checked ?? true,
            rate_limit: parseInt((document.getElementById('secSpamRate') || document.getElementById('secSpamLimit'))?.value || 5),
            time_window: 4,
            duplicate_limit: 3,
            action: document.getElementById('secSpamAction')?.value || 'timeout',
            timeout_mins: parseInt(document.getElementById('sec_spam_tm')?.value || 2)
        };

        const payload = {
            antinuke_active: document.getElementById('antinukeToggle')?.checked ?? true,
            security_settings: {
                limits: limitsData,
                instant: instantData,
                detect: detectData,
                antiraid: antiraidData,
                antispam: antispamData
            }
        };

        fetch(`/api/guild/${currentGuildId}/security/update`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(payload)
        }).then(r => r.json()).then(res => {
            showToast("✅ Security Matrix Saved Successfully!");
            loadAntinukeSettings();
        }).catch(err => {
            showToast("❌ Error saving security matrix");
        }).finally(() => {
            if (saveBtn) {
                saveBtn.disabled = false;
                saveBtn.innerHTML = origHtml;
            }
            if (topSaveBtn) {
                topSaveBtn.disabled = false;
                topSaveBtn.innerHTML = origHtml;
            }
        });

    } catch (e) {
        showToast("❌ Error saving security matrix");
        console.error(e);
        if (saveBtn) {
            saveBtn.disabled = false;
            saveBtn.innerHTML = origHtml;
        }
        if (topSaveBtn) {
            topSaveBtn.disabled = false;
            topSaveBtn.innerHTML = origHtml;
        }
    }
}

async function loadAntinukeSettings() {
    try {
        const resp = await fetch(`/api/guild/${currentGuildId}/security`);
        const data = await resp.json();
        if (data.success) {
            const tgl = document.getElementById('antinukeToggle');
            if (tgl) {
                tgl.checked = Boolean(data.antinuke_active);
                updateAntinukeBadge(Boolean(data.antinuke_active));
            }
            
            const cfg = data.security_settings || {};
            const limits = cfg.limits || {};
            Object.keys(limits).forEach(k => {
                const limitInput = document.getElementById(`sec_lim_${k}_val`) || document.getElementById(`sec_lim_${k}`);
                const punSelect = document.getElementById(`sec_lim_${k}_pun`);
                const tmInput = document.getElementById(`sec_lim_${k}_tm`);
                const tmWrap = document.getElementById(`sec_lim_${k}_tm_wrap`);
                const tgl = document.getElementById(`sec_lim_${k}_en`) || document.getElementById(`sec_lim_${k}_tgl`);
                
                if (limitInput) limitInput.value = limits[k].limit || 3;
                if (punSelect) {
                    punSelect.value = limits[k].punishment || 'ban';
                    if (tmWrap) {
                        tmWrap.style.display = punSelect.value === 'timeout' ? 'inline-flex' : 'none';
                    }
                }
                if (tmInput) tmInput.value = limits[k].timeout_mins || 10;
                if (tgl) tgl.checked = limits[k].enabled !== false;
            });
            
            const instant = cfg.instant || {};
            Object.keys(instant).forEach(k => {
                const punSelect = document.getElementById(`sec_inst_${k}_pun`);
                const tmInput = document.getElementById(`sec_inst_${k}_tm`);
                const tmWrap = document.getElementById(`sec_inst_${k}_tm_wrap`);
                const tgl = document.getElementById(`sec_inst_${k}_en`) || document.getElementById(`sec_inst_${k}_tgl`);
                
                if (punSelect) {
                    punSelect.value = instant[k].punishment || 'kick';
                    if (tmWrap) {
                        tmWrap.style.display = punSelect.value === 'timeout' ? 'inline-flex' : 'none';
                    }
                }
                if (tmInput) tmInput.value = instant[k].timeout_mins || 10;
                if (tgl) tgl.checked = instant[k].enabled !== false;
            });
            
            const detect = cfg.detect || {};
            const invTgl = document.getElementById('sec_det_invite_link_en') || document.getElementById('sec_det_invite_tgl');
            if (invTgl) invTgl.checked = detect.invite_link?.enabled !== false;
            const ghostTgl = document.getElementById('sec_det_ghost_ping_en') || document.getElementById('sec_det_ghost_tgl');
            if (ghostTgl) ghostTgl.checked = detect.ghost_ping?.enabled !== false;
            
            const raid = cfg.antiraid || {};
            if (document.getElementById('antiRaidToggle')) document.getElementById('antiRaidToggle').checked = raid.enabled !== false;
            const raidThresh = document.getElementById('secRaidThreshold') || document.getElementById('secRaidLimit');
            if (raidThresh) raidThresh.value = raid.join_threshold || 5;
            if (document.getElementById('secRaidAction')) {
                document.getElementById('secRaidAction').value = raid.action || 'kick';
                const raidWrap = document.getElementById('sec_raid_tm_wrap');
                if (raidWrap) raidWrap.style.display = raid.action === 'timeout' ? 'inline-flex' : 'none';
            }
            if (document.getElementById('sec_raid_tm')) document.getElementById('sec_raid_tm').value = raid.timeout_mins || 10;
            
            const spam = cfg.antispam || {};
            if (document.getElementById('antiSpamToggle')) document.getElementById('antiSpamToggle').checked = spam.enabled !== false;
            const spamRate = document.getElementById('secSpamRate') || document.getElementById('secSpamLimit');
            if (spamRate) spamRate.value = spam.rate_limit || 5;
            if (document.getElementById('secSpamAction')) {
                document.getElementById('secSpamAction').value = spam.action || 'timeout';
                const spamWrap = document.getElementById('sec_spam_tm_wrap');
                if (spamWrap) spamWrap.style.display = spam.action === 'timeout' ? 'inline-flex' : 'none';
            }
            if (document.getElementById('sec_spam_tm')) document.getElementById('sec_spam_tm').value = spam.timeout_mins || 2;

            renderWhitelist(data.whitelist || []);
            
            // Channels
            const serverLogs = data.server_logs || {};
            const keys = ['deleted', 'banned', 'timeouts', 'whitelisted', 'antinuke', 'abuse', 'antiraid', 'antispam', 'roles', 'channels'];
            let linkedCount = 0;
            keys.forEach(k => {
                const el = document.getElementById(`log_audit-${k}`);
                if (el) {
                    if (serverLogs[`audit-${k}`]) {
                        el.innerHTML = `<span style="color: #34d399;">● Linked</span>`;
                        linkedCount++;
                    } else {
                        el.innerHTML = `<span style="color: #f87171;">○ Missing</span>`;
                    }
                }
            });
        }
    } catch (e) {
        console.error("loadAntinukeSettings error:", e);
    }
}"""

if old_limits_pattern.search(js):
    js = old_limits_pattern.sub(new_limits_block, js)
    print("Replaced saveLimits and loadAntinukeSettings successfully!")
else:
    print("WARNING: old_limits_pattern not matched!")

with open(js_path, 'w', encoding='utf-8') as f:
    f.write(js)

print("script.js patched!")
