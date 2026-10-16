// Friday Dashboard Client Script
let currentGuildId = null;
let currentGuildMembers = [];
let currentGuildChannels = [];
let currentGuildRoles = [];
let currentGuildCategories = [];
let currentServerEmojis = [];
let currentEmojiTab = 'all';
let emojiSearchQuery = '';
let emojiSelectCallback = null;
let rrMappings = []; // Array of { id, emoji, roleId }
let rrMappingCounter = 0;
let currentBotAvatar = null;
let currentBotName = "Friday";
let currentRrColor = "#2dd4bf";
let currentRrShowThumbnail = false;
let currentRrFooterText = "React below to claim your roles!";

// Announcement state
let currentAnnColor = "#2dd4bf";
let currentAnnShowThumbnail = true;
let currentAnnFooterText = "Friday Broadcast System • Official Notification";
let currentAnnPing = "none";
let configuredAnnChannelId = null;

const STANDARD_EMOJI_LIBRARY = [
    // Support, Tickets, Help & Server Infrastructure (Ticket King style)
    { char: '🍵', name: 'tea green matcha drink cafe support' },
    { char: '🎫', name: 'ticket pass entry support help' },
    { char: '🎟️', name: 'tickets admission cinema pass' },
    { char: '🎪', name: 'circus tent event carnival festival' },
    { char: '🐰', name: 'rabbit bunny animal cute giveaway' },
    { char: '🌺', name: 'flower hibiscus promo partnership beauty' },
    { char: '🎴', name: 'cards flower support game hanafuda' },
    { char: '📜', name: 'scroll report rule rules paper document' },
    { char: '📌', name: 'pin notice pushpin bookmark' },
    { char: '📍', name: 'pin location round point' },
    { char: '🔔', name: 'bell notification alert chime' },
    { char: '🔕', name: 'bell muted silence quiet off' },
    { char: '📢', name: 'megaphone announcement broadcast speaker' },
    { char: '📣', name: 'cheering megaphone alert shout news' },
    { char: '💬', name: 'chat comment speech message discussion' },
    { char: '💭', name: 'thought bubble think idea' },
    { char: '📩', name: 'envelope incoming mail ticket inbox' },
    { char: '✉️', name: 'envelope mail letter email direct' },
    { char: '📦', name: 'package box delivery parcel claim' },
    { char: '🎁', name: 'gift present giveaway reward win bonus' },
    { char: '🏷️', name: 'label tag promo discount sale' },
    { char: '💡', name: 'lightbulb idea tip advice guide' },
    { char: '🛠️', name: 'tools hammer wrench config admin setup' },
    { char: '🔧', name: 'wrench repair fix settings support' },
    { char: '⚙️', name: 'gear settings cog control engine' },
    { char: '⚖️', name: 'scales justice rules law report balance' },
    { char: '🚨', name: 'police siren emergency alert report warning' },
    { char: '👮', name: 'officer mod staff police admin' },
    { char: '🤝', name: 'handshake partnership deal promo affiliate' },
    { char: '💼', name: 'briefcase work corporate promo business job' },
    { char: '💰', name: 'money bag cash coin claim prize reward' },
    { char: '💎', name: 'gem diamond premium boost vip luxury' },
    { char: '👑', name: 'crown king vip owner royal gold' },
    { char: '🛡️', name: 'shield security protect antinuke guard' },
    { char: '🔒', name: 'lock private secure closed secret' },
    { char: '🔓', name: 'unlock public unprivate open access' },
    { char: '🔑', name: 'key access login password code' },
    { char: '⭐', name: 'star favorite rank level gold top' },
    { char: '🌟', name: 'glowing star sparkle bright shine' },
    { char: '✨', name: 'sparkles magic beauty aesthetic shine' },
    { char: '🏆', name: 'trophy champion win level top winner first' },
    { char: '🥇', name: 'first medal gold winner champion' },
    { char: '🥈', name: 'second medal silver rank runner' },
    { char: '🥉', name: 'third medal bronze rank' },
    { char: '🎉', name: 'party popper celebrate celebration cheer' },
    { char: '🎊', name: 'confetti ball celebration party fiesta' },
    { char: '🔥', name: 'fire hot trending lit flame' },
    { char: '⚡', name: 'lightning bolt zap energy fast power' },
    { char: '🚀', name: 'rocket boost fast launch speed ship' },
    { char: '🎯', name: 'target bullseye goal objective aim' },
    { char: '💯', name: 'hundred percent perfect score stamp' },
    { char: '✅', name: 'check mark tick success verified approve' },
    { char: '✔️', name: 'check mark light approve ok done' },
    { char: '❌', name: 'cross mark red no cancel decline error' },
    { char: '⛔', name: 'no entry stop denied forbidden reject' },
    { char: '🚫', name: 'prohibited ban block stop disallowed' },
    { char: '⚠️', name: 'warning danger caution notice alert' },
    { char: 'ℹ️', name: 'info information guide manual details' },
    { char: '❓', name: 'question mark help faq inquiry ask' },
    { char: '❗', name: 'exclamation mark alert urgent attention' },

    // Cute Animals & Aesthetics
    { char: '🐶', name: 'dog puppy animal cute pet doggo shiba' },
    { char: '🐕', name: 'dog shiba inu pet animal' },
    { char: '🐱', name: 'cat kitten animal cute pet meow' },
    { char: '🦊', name: 'fox animal cute orange kit' },
    { char: '🐻', name: 'bear teddy animal cute fluffy' },
    { char: '🐼', name: 'panda animal cute bamboo bear' },
    { char: '🐨', name: 'koala animal cute bear' },
    { char: '🐯', name: 'tiger animal cute rawr' },
    { char: '🦁', name: 'lion animal king mane' },
    { char: '🦄', name: 'unicorn magic fantasy aesthetic horn' },
    { char: '🦋', name: 'butterfly beauty wings aesthetic blue' },
    { char: '🌸', name: 'cherry blossom flower aesthetic pink sakura' },
    { char: '🌹', name: 'rose red flower love aesthetic' },
    { char: '🌻', name: 'sunflower happy summer yellow flower' },
    { char: '🍀', name: 'four leaf clover luck lucky green' },
    { char: '🐾', name: 'paw prints pet animal cat dog paws' },

    // Gaming, Media & Fun
    { char: '🎮', name: 'gamepad gaming play game console controller' },
    { char: '👾', name: 'alien monster retro arcade space invader' },
    { char: '🕹️', name: 'joystick arcade gaming retro stick' },
    { char: '🎲', name: 'dice random chance game roll' },
    { char: '🎵', name: 'musical note music song sound tune' },
    { char: '🎶', name: 'notes musical music audio melodic' },
    { char: '🎧', name: 'headphones listen audio sound track' },

    // Hearts & Expressions
    { char: '❤️', name: 'heart red love passion' },
    { char: '💖', name: 'sparkling heart love cute shine' },
    { char: '💜', name: 'purple heart love aesthetic violet' },
    { char: '💙', name: 'blue heart love trust ocean' },
    { char: '🖤', name: 'black heart dark aesthetic emo' },
    { char: '🤍', name: 'white heart pure aesthetic angel' },
    { char: '💕', name: 'two hearts love cute floating' },
    { char: '🥰', name: 'smiling face with hearts love cute adore' },
    { char: '😍', name: 'heart eyes love enamored romantic' },
    { char: '😎', name: 'cool sunglasses chill rad awesome' },
    { char: '🫡', name: 'salute respect yes sir captain roger' },
    { char: '🥳', name: 'party face celebrate happy blow horn' },
    { char: '🤩', name: 'star eyes excited amazed wow' },
    { char: '😊', name: 'smiling happy blush gentle warm' },
    { char: '🥺', name: 'pleading face puppy eyes cute please' },
    { char: '😭', name: 'loudly crying tears sobbing sad bawling' },
    { char: '😂', name: 'joy tears laughing lol rofl funny haha' },
    { char: '🤣', name: 'rofl rolling on the floor laughing hilarious' },
    { char: '💀', name: 'skull dead lol dying rip' },
    { char: '👀', name: 'eyes looking watching inspect observe see' },
    { char: '💪', name: 'flex bicep strong power workout gym' },
    { char: '👏', name: 'clapping hands applause bravo praise' },
    { char: '🙌', name: 'raising hands praise celebration hooray' },
    { char: '👍', name: 'thumbs up like agree ok positive' },
    { char: '👎', name: 'thumbs down dislike disagree negative' },
    { char: '☕', name: 'coffee hot drink morning relax cup' },
    { char: '🧋', name: 'boba bubble tea drink cute straw milk' },
    { char: '🍰', name: 'cake sweet dessert birthday treat' }
];

const POPULAR_STANDARD_EMOJIS = STANDARD_EMOJI_LIBRARY.map(e => e.char);

// DOM References
const guildDropdown = document.getElementById('guildDropdown');
const guildHeader = document.getElementById('guildHeader');
const guildList = document.getElementById('guildList');
const guildNameDisplay = document.getElementById('guildNameDisplay');
const guildIconSmall = document.getElementById('guildIconSmall');
const emptyState = document.getElementById('emptyState');
const tabs = document.querySelectorAll('.nav-item');
const tabContents = document.querySelectorAll('.tab-content');
const breadcrumbCurrent = document.getElementById('breadcrumbCurrent');
const toast = document.getElementById('toast');
const toastMessage = document.getElementById('toastMessage');

// Emoji Picker Elements
const emojiPickerBtn = document.getElementById('emojiPickerBtn');
const emojiPopover = document.getElementById('emojiPopover');
const emojiSearchInput = document.getElementById('emojiSearchInput');
const serverEmojiGrid = document.getElementById('serverEmojiGrid');
const emojiCountBadge = document.getElementById('emojiCountBadge');
const emojiFilterSummary = document.getElementById('emojiFilterSummary');

// Tab Titles Map for Breadcrumb
const tabTitles = {
    'antinukeSection': 'Anti-Nuke Protection',
    'privacySection': 'Channel & Category Privacy',
    'antiabuseSection': 'Anti-Abuse Filter',
    'levelingSection': 'Leveling System',
    'reactionRolesSection': 'Reaction Roles',
    'announcementsSection': 'Announcements Dispatcher',
    'ticketsSection': 'Ticket System Setup',
    'responsesSection': 'Custom Bot Responses',
    'automationsSection': 'Auto-React & Auto-Responder',
    'firstWelcomeSection': 'First Chat Welcome',
    'afkSection': 'AFK System & Pings'
};

// ───────────────────── Bot Profile & Avatar Sync ─────────────────────
async function loadBotProfile() {
    try {
        const resp = await fetch('/api/bot/profile');
        const data = await resp.json();
        if (data.avatar) {
            currentBotAvatar = data.avatar;
            updateBotAvatars(data.avatar);
        }
        if (data.name) {
            currentBotName = data.name;
            document.querySelectorAll('.bot-name, .discord-bot-name').forEach(el => {
                el.textContent = data.name;
            });
        }
    } catch (e) { }
}

function updateBotAvatars(avatarUrl) {
    if (!avatarUrl) return;
    const sidebarAvatars = document.querySelectorAll('.bot-avatar');
    sidebarAvatars.forEach(el => {
        el.innerHTML = `<img src="${avatarUrl}" alt="${currentBotName}">`;
    });
    const discordAvatars = document.querySelectorAll('.discord-avatar');
    discordAvatars.forEach(el => {
        el.innerHTML = `<img src="${avatarUrl}" alt="${currentBotName}">`;
    });
}

// ───────────────────── Initialization ─────────────────────
document.addEventListener('DOMContentLoaded', () => {
    loadBotProfile();
    loadGuilds();
    setupEventListeners();
    initCustomSelects();
    initAllRichEmojiEditors();
});

function setupEventListeners() {


    
    // Dropdown toggle
    guildHeader.addEventListener('click', () => guildDropdown.classList.toggle('open'));
    document.addEventListener('click', (e) => {
        if (!guildDropdown.contains(e.target)) guildDropdown.classList.remove('open');
    });

    // Tab Navigation
    tabs.forEach(tab => {
        tab.addEventListener('click', (e) => {
            e.preventDefault();
            if (!currentGuildId) return showToast('⚠️ Select a server first!');

            tabs.forEach(t => t.classList.remove('active'));
            tabContents.forEach(c => c.style.display = 'none');

            tab.classList.add('active');
            const targetId = tab.dataset.tab;
            const target = document.getElementById(targetId);
            if (target) {
                target.style.display = 'block';
                if (breadcrumbCurrent && tabTitles[targetId]) {
                    breadcrumbCurrent.textContent = tabTitles[targetId];
                }
            }
            const topSaveBtn = document.getElementById('topSaveSecurityBtn');
            if (topSaveBtn) {
                topSaveBtn.style.display = targetId === 'antinukeSection' ? 'inline-flex' : 'none';
            }
            loadDataForActiveTab();
        });
    });

    // Sync Button
    document.querySelectorAll('.syncBtn').forEach(btn => {
        btn.addEventListener('click', () => {
            const icon = btn.querySelector('svg');
            if (icon) {
                icon.style.transform = 'rotate(180deg)';
                icon.style.transition = 'transform 0.4s ease';
            }
            Promise.all([loadBotProfile(), loadCoreData()]).then(() => {
                loadDataForActiveTab();
                showToast("🔄 State & Profile synchronized with Friday!");
                setTimeout(() => {
                    if (icon) {
                        icon.style.transform = 'rotate(0deg)';
                        icon.style.transition = 'none';
                    }
                }, 400);
            });
        });
    });

    // Anti-Nuke Handlers
    const antinukeTgl = document.getElementById('antinukeToggle');
    if (antinukeTgl) antinukeTgl.addEventListener('change', toggleAntinuke);
    
    const saveLimitsBtn = document.getElementById('saveLimitsBtn');
    if (saveLimitsBtn) saveLimitsBtn.addEventListener('click', saveLimits);

    // Custom Responses Event Listeners (Emoji picker & variable inserters)
    document.querySelectorAll('.resp-var-badge').forEach(badge => {
        badge.addEventListener('click', (e) => {
            e.preventDefault();
            e.stopPropagation();
            const targetId = badge.getAttribute('data-target');
            const varText = badge.getAttribute('data-var') || badge.textContent;
            const input = document.getElementById(targetId);
            if (!input) return;
            const start = input.selectionStart ?? input.value.length;
            const end = input.selectionEnd ?? input.value.length;
            input.value = input.value.substring(0, start) + varText + input.value.substring(end);
            input.focus();
            input.selectionStart = input.selectionEnd = start + varText.length;
            input.dispatchEvent(new Event('input', { bubbles: true }));
        });
    });

    document.querySelectorAll('.resp-emoji-btn').forEach(btn => {
        btn.addEventListener('click', (e) => {
            e.preventDefault();
            e.stopPropagation();
            const targetId = btn.getAttribute('data-target');
            const input = document.getElementById(targetId);
            if (!input) return;
            openEmojiPicker(btn, (emojiVal) => {
                const start = input.selectionStart ?? input.value.length;
                const end = input.selectionEnd ?? input.value.length;
                input.value = input.value.substring(0, start) + emojiVal + ' ' + input.value.substring(end);
                input.focus();
                input.selectionStart = input.selectionEnd = start + emojiVal.length + 1;
                input.dispatchEvent(new Event('input', { bubbles: true }));
            });
        });
    });

    const saveRespBtn = document.getElementById('saveResponsesBtn') || document.getElementById('saveCustomResponsesBtn');
    if (saveRespBtn) {
        saveRespBtn.addEventListener('click', saveResponsesSettings);
    }

    const saveAiThinkingBtn = document.getElementById('saveAiThinkingBtn');
    if (saveAiThinkingBtn) {
        saveAiThinkingBtn.addEventListener('click', async () => {
            const autoVal = document.getElementById('autoAiThinkingInput')?.value?.trim();
            const respInput = document.getElementById('resp_ai_thinking');
            if (respInput && autoVal !== undefined) {
                respInput.value = autoVal;
            }
            await saveResponsesSettings();
        });
    }

    const autoAiInput = document.getElementById('autoAiThinkingInput');
    const respAiInput = document.getElementById('resp_ai_thinking');
    if (autoAiInput && respAiInput) {
        autoAiInput.addEventListener('input', () => { respAiInput.value = autoAiInput.value; });
        respAiInput.addEventListener('input', () => { autoAiInput.value = respAiInput.value; });
    }
    
    const topSaveBtn = document.getElementById('topSaveSecurityBtn');
    if (topSaveBtn) {
        topSaveBtn.addEventListener('click', saveLimits);
    }
    
    const wlAddBtn = document.getElementById('whitelistAddBtn');
    if (wlAddBtn) wlAddBtn.addEventListener('click', () => addWhitelistUser('antinuke'));

    const raidTgl = document.getElementById('antiRaidToggle');
    if (raidTgl) {
        raidTgl.addEventListener('change', async (e) => {
            try {
                await fetch(`/api/guild/${currentGuildId}/security/antiraid`, {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ enabled: e.target.checked })
                });
                showToast(e.target.checked ? "🚨 Anti-Raid System Activated" : "⚠️ Anti-Raid System Paused");
            } catch (err) {}
        });
    }

    const spamTgl = document.getElementById('antiSpamToggle');
    if (spamTgl) {
        spamTgl.addEventListener('change', async (e) => {
            try {
                await fetch(`/api/guild/${currentGuildId}/security/antispam`, {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ enabled: e.target.checked })
                });
                showToast(e.target.checked ? "💬 Anti-Spam System Activated" : "⚠️ Anti-Spam System Paused");
            } catch (err) {}
        });
    }

    
    // Wire all 21 punishment select dropdowns to show/hide TM input dynamically
    const limitKeys = ['ban', 'kick', 'role_create', 'role_delete', 'channel_create', 'channel_delete', 'mention'];
    limitKeys.forEach(k => {
        const sel = document.getElementById(`sec_lim_${k}_pun`);
        const wrap = document.getElementById(`sec_lim_${k}_tm_wrap`);
        if (sel && wrap) {
            sel.addEventListener('change', () => {
                wrap.style.display = sel.value === 'timeout' ? 'flex' : 'none';
            });
        }
    });

    const instantKeys = [
        'bot_add', 'prune', 'dangerous_perms', 'dangerous_role_add',
        'vanity_change', 'server_rename', 'server_icon', 'role_rename',
        'channel_rename', 'emoji_delete', 'emoji_rename', 'invite_delete'
    ];
    instantKeys.forEach(k => {
        const sel = document.getElementById(`sec_inst_${k}_pun`);
        const wrap = document.getElementById(`sec_inst_${k}_tm_wrap`);
        if (sel && wrap) {
            sel.addEventListener('change', () => {
                wrap.style.display = sel.value === 'timeout' ? 'flex' : 'none';
            });
        }
    });

    const raidSel = document.getElementById('secRaidAction');
    const raidWrap = document.getElementById('sec_raid_tm_wrap');
    if (raidSel && raidWrap) {
        raidSel.addEventListener('change', () => {
            raidWrap.style.display = raidSel.value === 'timeout' ? 'flex' : 'none';
        });
    }

    const spamSel = document.getElementById('secSpamAction');
    const spamWrap = document.getElementById('sec_spam_tm_wrap');
    if (spamSel && spamWrap) {
        spamSel.addEventListener('change', () => {
            spamWrap.style.display = spamSel.value === 'timeout' ? 'flex' : 'none';
        });
    }

    // Initialize Custom Responses Emoji Buttons & Variable Badges
    initCustomResponsesControls();

    const refreshSecBtn = document.getElementById('secCreateChannelsBtn') || document.getElementById('refreshSecurityChannelsBtn');
    if (refreshSecBtn) {
        refreshSecBtn.addEventListener('click', async () => {
            if (!currentGuildId) return showToast("⚠️ Select a server first!");
            refreshSecBtn.disabled = true;
            const origText = refreshSecBtn.innerHTML;
            refreshSecBtn.innerHTML = `<span>⏳</span> Creating Channels...`;
            try {
                const resp = await fetch(`/api/guild/${currentGuildId}/antinuke/refresh`, { method: 'POST' });
                const data = await resp.json();
                if (data.success) {
                    showToast(`🛡️ Created ${data.created || 0} missing log channels!`);
                    await loadAntinukeSettings();
                } else {
                    showToast(`❌ Error: ${data.error || 'Failed to create channels'}`);
                }
            } catch (e) {
                showToast("❌ Network error creating security channels");
            } finally {
                refreshSecBtn.disabled = false;
                refreshSecBtn.innerHTML = origText;
            }
        });
    }

    const syncSecBtn = document.getElementById('secSyncChannelsBtn') || document.getElementById('syncSecurityChannelsBtn');
    if (syncSecBtn) {
        syncSecBtn.addEventListener('click', async () => {
            if (!currentGuildId) return showToast("⚠️ Select a server first!");
            syncSecBtn.disabled = true;
            const origText = syncSecBtn.innerHTML;
            syncSecBtn.innerHTML = `<span>⏳</span> Scanning & Linking...`;
            try {
                const resp = await fetch(`/api/guild/${currentGuildId}/antinuke/sync`, { method: 'POST' });
                const data = await resp.json();
                if (data.success) {
                    showToast(`🛡️ Security sync complete! Linked ${data.count} channels.`);
                    await loadAntinukeSettings();
                } else {
                    showToast(`❌ Error: ${data.error || 'Failed to sync'}`);
                }
            } catch (e) {
                showToast("❌ Network error syncing security channels");
            } finally {
                syncSecBtn.disabled = false;
                syncSecBtn.innerHTML = origText;
            }
        });
    }

    // Feature Whitelist Popover & Drawer Interactions
    setupFeatureWhitelistEvents();

    // Leveling Mode Segment Buttons
    document.querySelectorAll('#levelModeGroup .mode-segment-btn').forEach(btn => {
        btn.addEventListener('click', () => {
            document.querySelectorAll('#levelModeGroup .mode-segment-btn').forEach(b => b.classList.remove('active'));
            btn.classList.add('active');
            const mode = btn.dataset.mode || 'both';
            const input = document.getElementById('levelModeInput');
            if (input) input.value = mode;
            updateLevelPreview();
        });
    });

    // Leveling Handlers
    const slBtn = document.getElementById('saveLevelingBtn'); if (slBtn) slBtn.addEventListener('click', saveLeveling);
    const levelMsgInput = document.getElementById('levelMessageInput');
    if (levelMsgInput) {
        levelMsgInput.addEventListener('input', updateLevelPreview);
    }

    const levelChanSelect = document.getElementById('levelChannelSelect');
    if (levelChanSelect) {
        levelChanSelect.addEventListener('change', () => {
            const testChanSelect = document.getElementById('testChannelSelect');
            if (testChanSelect && !testChanSelect.value && levelChanSelect.value) {
                testChanSelect.value = levelChanSelect.value;
            }
        });
    }

    const sendTestMsgBtn = document.getElementById('sendTestMsgBtn');
    if (sendTestMsgBtn) {
        sendTestMsgBtn.addEventListener('click', async () => {
            const targetChannelId = document.getElementById('testChannelSelect').value || document.getElementById('levelChannelSelect').value;
            if (!targetChannelId) {
                return showToast('⚠️ Select a channel to send the test message to!');
            }
            const message = document.getElementById('levelMessageInput').value;
            if (!message.trim()) {
                return showToast('⚠️ Message template is empty!');
            }

            sendTestMsgBtn.disabled = true;
            sendTestMsgBtn.innerHTML = `<span>⏳</span> Dispatching...`;

            try {
                const resp = await fetch(`/api/guild/${currentGuildId}/leveling/test`, {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ channel: targetChannelId, message: message })
                });
                const data = await resp.json();
                if (data.success) {
                    showToast(`🚀 Test message posted in #${data.channel_name}!`);
                    const status = document.getElementById('testMsgStatus');
                    if (status) {
                        status.style.opacity = '1';
                        setTimeout(() => status.style.opacity = '0', 2500);
                    }
                } else {
                    showToast(`❌ Error: ${data.error || 'Failed to dispatch test message'}`);
                }
            } catch (err) {
                showToast(`❌ Network error dispatching test message`);
            } finally {
                sendTestMsgBtn.disabled = false;
                sendTestMsgBtn.innerHTML = `
                    <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><line x1="22" y1="2" x2="11" y2="13"/><polygon points="22 2 15 22 11 13 2 9 22 2"/></svg>
                    Send Test to Server
                `;
            }
        });
    }

    // Global Emoji Picker Event Listeners
    if (emojiPickerBtn && emojiPopover) {
        emojiPickerBtn.addEventListener('click', (e) => {
            e.stopPropagation();
            openEmojiPicker(emojiPickerBtn, (val) => insertVariable(val));
        });

        document.addEventListener('click', (e) => {
            if (!emojiPopover.contains(e.target) && 
                !e.target.closest('.emoji-picker-btn') && 
                !e.target.closest('.rr-emoji-preview-btn') && 
                !e.target.closest('.resp-emoji-btn') && 
                !e.target.closest('.btn-emoji-trigger')) {
                closeEmojiPicker();
            }
        });

        if (emojiSearchInput) {
            emojiSearchInput.addEventListener('input', (e) => {
                emojiSearchQuery = e.target.value.toLowerCase().trim();
                renderEmojiGrid();
            });
        }

        document.querySelectorAll('.emoji-tab').forEach(tab => {
            tab.addEventListener('click', (e) => {
                document.querySelectorAll('.emoji-tab').forEach(t => t.classList.remove('active'));
                tab.classList.add('active');
                currentEmojiTab = tab.dataset.tab;
                renderEmojiGrid();
            });
        });
    }

    // Reaction Roles Event Listeners
    const rrTitleEmojiBtn = document.getElementById('rrTitleEmojiBtn');
    if (rrTitleEmojiBtn) {
        rrTitleEmojiBtn.addEventListener('click', (e) => {
            e.stopPropagation();
            openEmojiPicker(rrTitleEmojiBtn, (val) => {
                const richEl = document.getElementById('rrTitleInput_rich');
                if (richEl) {
                    insertEmojiOrTextIntoRichEditor(richEl, val);
                    return;
                }
                const titleInput = document.getElementById('rrTitleInput');
                if (titleInput) {
                    const start = titleInput.selectionStart || titleInput.value.length;
                    const end = titleInput.selectionEnd || titleInput.value.length;
                    titleInput.value = titleInput.value.substring(0, start) + val + ' ' + titleInput.value.substring(end);
                    titleInput.focus();
                    titleInput.selectionStart = titleInput.selectionEnd = start + val.length + 1;
                    updateRrEmbedPreview();
                }
            });
        });
    }

    const rrDescEmojiBtn = document.getElementById('rrDescEmojiBtn');
    if (rrDescEmojiBtn) {
        rrDescEmojiBtn.addEventListener('click', (e) => {
            e.stopPropagation();
            openEmojiPicker(rrDescEmojiBtn, (val) => insertRrVar(val));
        });
    }

    // Reaction Theme Presets & Custom Colors
    document.querySelectorAll('.rr-theme-chip').forEach(chip => {
        chip.addEventListener('click', () => {
            document.querySelectorAll('.rr-theme-chip').forEach(c => c.classList.remove('active'));
            chip.classList.add('active');
            currentRrColor = chip.dataset.color;
            const customCol = document.getElementById('rrCustomColorInput');
            const hexCode = document.getElementById('rrColorHexCode');
            if (customCol) customCol.value = currentRrColor;
            if (hexCode) hexCode.textContent = currentRrColor;
            updateRrEmbedPreview();
        });
    });

    const customColorInput = document.getElementById('rrCustomColorInput');
    if (customColorInput) {
        customColorInput.addEventListener('input', (e) => {
            currentRrColor = e.target.value;
            const hexCode = document.getElementById('rrColorHexCode');
            if (hexCode) hexCode.textContent = currentRrColor;
            document.querySelectorAll('.rr-theme-chip').forEach(c => {
                c.classList.toggle('active', c.dataset.color.toLowerCase() === currentRrColor.toLowerCase());
            });
            updateRrEmbedPreview();
        });
    }

    const thumbCheckbox = document.getElementById('rrThumbnailCheckbox');
    if (thumbCheckbox) {
        thumbCheckbox.addEventListener('change', (e) => {
            currentRrShowThumbnail = e.target.checked;
            updateRrEmbedPreview();
        });
    }

    const footerInput = document.getElementById('rrFooterInput');
    if (footerInput) {
        footerInput.addEventListener('input', (e) => {
            currentRrFooterText = e.target.value;
            updateRrEmbedPreview();
        });
    }

    const addRrMappingBtn = document.getElementById('addRrMappingBtn');
    if (addRrMappingBtn) {
        addRrMappingBtn.addEventListener('click', () => addRrMappingRow());
    }

    const deployReactionPanelBtn = document.getElementById('deployReactionPanelBtn');
    if (deployReactionPanelBtn) {
        deployReactionPanelBtn.addEventListener('click', deployReactionPanel);
    }
    
    const deployTicketPanelBtn = document.getElementById('deployTicketPanelBtn');
    if (deployTicketPanelBtn) {
        deployTicketPanelBtn.addEventListener('click', deployTicketPanel);
    }

    const saveTicketConfigBtn = document.getElementById('saveTicketConfigBtn');
    if (saveTicketConfigBtn) {
        saveTicketConfigBtn.addEventListener('click', saveTicketConfig);
    }

    // Ticket Real-Time Simulator Listeners
    ['ticketTitleInput', 'ticketDescInput', 'ticketBtn1', 'ticketBtn2', 'ticketBtn3', 'ticketBtn4'].forEach(id => {
        const el = document.getElementById(id);
        if (el) el.addEventListener('input', updateTicketPreview);
    });

    const ticketTitleEmojiBtn = document.getElementById('ticketTitleEmojiBtn');
    if (ticketTitleEmojiBtn) {
        ticketTitleEmojiBtn.addEventListener('click', (e) => {
            e.stopPropagation();
            openEmojiPicker(ticketTitleEmojiBtn, (val) => {
                const richEl = document.getElementById('ticketTitleInput_rich');
                if (richEl) {
                    insertEmojiOrTextIntoRichEditor(richEl, val);
                    return;
                }
                const titleInput = document.getElementById('ticketTitleInput');
                if (titleInput) {
                    const start = titleInput.selectionStart || titleInput.value.length;
                    const end = titleInput.selectionEnd || titleInput.value.length;
                    titleInput.value = titleInput.value.substring(0, start) + val + ' ' + titleInput.value.substring(end);
                    titleInput.focus();
                    titleInput.selectionStart = titleInput.selectionEnd = start + val.length + 1;
                    updateTicketPreview();
                }
            });
        });
    }

    const ticketDescEmojiBtn = document.getElementById('ticketDescEmojiBtn');
    if (ticketDescEmojiBtn) {
        ticketDescEmojiBtn.addEventListener('click', (e) => {
            e.stopPropagation();
            openEmojiPicker(ticketDescEmojiBtn, (val) => insertTicketVar(val));
        });
    }

    const ticketBtns = [1, 2, 3, 4];
    ticketBtns.forEach(num => {
        const btn = document.getElementById(`ticketBtn${num}EmojiBtn`);
        if (btn) {
            btn.addEventListener('click', (e) => {
                e.stopPropagation();
                openEmojiPicker(btn, (val) => {
                    setTicketButtonEmoji(num, val);
                });
            });
        }
    });

    // Ticket Theme chips
    document.querySelectorAll('.ticket-theme-chip').forEach(chip => {
        chip.addEventListener('click', () => {
            document.querySelectorAll('.ticket-theme-chip').forEach(c => c.classList.remove('active'));
            chip.classList.add('active');
            currentTicketColor = chip.dataset.color;
            const customCol = document.getElementById('ticketCustomColorInput');
            const hexCode = document.getElementById('ticketColorHexCode');
            if (customCol) customCol.value = currentTicketColor;
            if (hexCode) hexCode.textContent = currentTicketColor;
            updateTicketPreview();
        });
    });

    const ticketCustomColorInput = document.getElementById('ticketCustomColorInput');
    if (ticketCustomColorInput) {
        ticketCustomColorInput.addEventListener('input', (e) => {
            currentTicketColor = e.target.value;
            const hexCode = document.getElementById('ticketColorHexCode');
            if (hexCode) hexCode.textContent = currentTicketColor;
            document.querySelectorAll('.ticket-theme-chip').forEach(c => {
                c.classList.toggle('active', c.dataset.color.toLowerCase() === currentTicketColor.toLowerCase());
            });
            updateTicketPreview();
        });
    }

    const ticketTranscriptToggle = document.getElementById('ticketTranscriptToggle');
    if (ticketTranscriptToggle) {
        ticketTranscriptToggle.addEventListener('change', (e) => {
            const wrapper = document.getElementById('ticketTranscriptCategoryWrapper');
            if (wrapper) {
                wrapper.style.opacity = e.target.checked ? '1' : '0.4';
                wrapper.style.pointerEvents = e.target.checked ? 'auto' : 'none';
            }
        });
    }

    const rrTitleInput = document.getElementById('rrTitleInput');
    if (rrTitleInput) {
        rrTitleInput.addEventListener('input', updateRrEmbedPreview);
    }

    const rrDescInput = document.getElementById('rrDescInput');
    if (rrDescInput) {
        rrDescInput.addEventListener('input', updateRrEmbedPreview);
    }

    // Announcements Event Listeners
    const saveAnnChannelBtn = document.getElementById('saveAnnChannelBtn');
    if (saveAnnChannelBtn) {
        saveAnnChannelBtn.addEventListener('click', saveAnnouncementChannel);
    }

    const annTitleEmojiBtn = document.getElementById('annTitleEmojiBtn');
    if (annTitleEmojiBtn) {
        annTitleEmojiBtn.addEventListener('click', (e) => {
            e.stopPropagation();
            openEmojiPicker(annTitleEmojiBtn, (val) => {
                const richEl = document.getElementById('annTitleInput_rich');
                if (richEl) {
                    insertEmojiOrTextIntoRichEditor(richEl, val);
                    return;
                }
                const titleInput = document.getElementById('annTitleInput');
                if (titleInput) {
                    const start = titleInput.selectionStart || titleInput.value.length;
                    const end = titleInput.selectionEnd || titleInput.value.length;
                    titleInput.value = titleInput.value.substring(0, start) + val + ' ' + titleInput.value.substring(end);
                    titleInput.focus();
                    titleInput.selectionStart = titleInput.selectionEnd = start + val.length + 1;
                    updateAnnPreview();
                }
            });
        });
    }

    const annContentEmojiBtn = document.getElementById('annContentEmojiBtn');
    if (annContentEmojiBtn) {
        annContentEmojiBtn.addEventListener('click', (e) => {
            e.stopPropagation();
            openEmojiPicker(annContentEmojiBtn, (val) => insertAnnVar(val));
        });
    }

    // Ping pills selection
    document.querySelectorAll('.ann-ping-pill').forEach(pill => {
        pill.addEventListener('click', () => {
            document.querySelectorAll('.ann-ping-pill').forEach(p => p.classList.remove('active'));
            pill.classList.add('active');
            currentAnnPing = pill.dataset.ping || 'none';
            const radio = pill.querySelector('input[type="radio"]');
            if (radio) radio.checked = true;
            updateAnnPreview();
        });
    });

    // Announcement theme presets & color picker
    document.querySelectorAll('.ann-theme-chip').forEach(chip => {
        chip.addEventListener('click', () => {
            document.querySelectorAll('.ann-theme-chip').forEach(c => c.classList.remove('active'));
            chip.classList.add('active');
            currentAnnColor = chip.dataset.color;
            const customCol = document.getElementById('annCustomColorInput');
            const hexCode = document.getElementById('annColorHexCode');
            if (customCol) customCol.value = currentAnnColor;
            if (hexCode) hexCode.textContent = currentAnnColor;
            updateAnnPreview();
        });
    });

    const annCustomColorInput = document.getElementById('annCustomColorInput');
    if (annCustomColorInput) {
        annCustomColorInput.addEventListener('input', (e) => {
            currentAnnColor = e.target.value;
            const hexCode = document.getElementById('annColorHexCode');
            if (hexCode) hexCode.textContent = currentAnnColor;
            document.querySelectorAll('.ann-theme-chip').forEach(c => {
                c.classList.toggle('active', c.dataset.color.toLowerCase() === currentAnnColor.toLowerCase());
            });
            updateAnnPreview();
        });
    }

    const annThumbnailCheckbox = document.getElementById('annThumbnailCheckbox');
    if (annThumbnailCheckbox) {
        annThumbnailCheckbox.addEventListener('change', (e) => {
            currentAnnShowThumbnail = e.target.checked;
            updateAnnPreview();
        });
    }

    const annFooterInput = document.getElementById('annFooterInput');
    if (annFooterInput) {
        annFooterInput.addEventListener('input', (e) => {
            currentAnnFooterText = e.target.value;
            updateAnnPreview();
        });
    }

    const annTitleInput = document.getElementById('annTitleInput');
    if (annTitleInput) {
        annTitleInput.addEventListener('input', updateAnnPreview);
    }

    const annContentInput = document.getElementById('annContentInput');
    if (annContentInput) {
        annContentInput.addEventListener('input', updateAnnPreview);
    }

    const broadcastAnnouncementBtn = document.getElementById('broadcastAnnouncementBtn');
    if (broadcastAnnouncementBtn) {
        broadcastAnnouncementBtn.addEventListener('click', broadcastAnnouncement);
    }

    // Anti-Abuse Handlers
    const wordInput = document.getElementById('bannedWordInput');
    if (wordInput) {
        wordInput.addEventListener('keydown', (e) => {
            if (e.key === 'Enter') {
                e.preventDefault();
                addBannedWord(e.target.value);
            }
        });
    }
    document.getElementById('abuseWhitelistAddBtn').addEventListener('click', () => addWhitelistUser('antiabuse'));

    // Privacy Handlers
    const initLockBtn = document.getElementById('initiateLockdownBtn');
    if (initLockBtn) initLockBtn.addEventListener('click', handleGlobalLockdown);

    const unlockAllBtn = document.getElementById('unlockAllChannelsBtn');
    if (unlockAllBtn) unlockAllBtn.addEventListener('click', handleUnlockAllChannels);

    const privChanBtn = document.getElementById('privChanBtn');
    if (privChanBtn) privChanBtn.addEventListener('click', handlePrivChan);

    const unprivChanBtn = document.getElementById('unprivChanBtn');
    if (unprivChanBtn) unprivChanBtn.addEventListener('click', handleUnprivChan);

    const privCatBtn = document.getElementById('privCatBtn');
    if (privCatBtn) privCatBtn.addEventListener('click', handlePrivCat);

    const unprivCatBtn = document.getElementById('unprivCatBtn');
    if (unprivCatBtn) unprivCatBtn.addEventListener('click', handleUnprivCat);

    const piBtn = document.getElementById('privacyIgnoreAddBtn'); if (piBtn) piBtn.addEventListener('click', addPrivacyIgnored);

    // Stop Bot Handler
    const stopBotBtn = document.getElementById('stopBotBtn');
    if (stopBotBtn) {
        stopBotBtn.addEventListener('click', async () => {
            if (confirm("Are you sure you want to shut down Friday and close the Dashboard?")) {
                try {
                    await fetch('/api/bot/stop', { method: 'POST' });
                    showToast("🔴 Shutting down Friday...");
                    setTimeout(() => {
                        document.body.innerHTML = `
                            <div style="display:flex; height:100vh; align-items:center; justify-content:center; flex-direction:column; color:white; font-family:'Plus Jakarta Sans',sans-serif; text-align:center;">
                                <div style="width:60px; height:60px; border-radius:50%; background:rgba(239,68,68,0.15); display:flex; align-items:center; justify-content:center; margin-bottom:16px;">
                                    <svg width="28" height="28" viewBox="0 0 24 24" fill="none" stroke="#ef4444" stroke-width="2"><circle cx="12" cy="12" r="10"/><rect x="9" y="9" width="6" height="6"/></svg>
                                </div>
                                <h1 style="font-size:24px; margin-bottom:8px;">Friday Has Stopped</h1>
                                <p style="color:#94a3b8; font-size:14px;">The process has terminated. You can safely close this browser tab.</p>
                            </div>
                        `;
                    }, 1000);
                } catch (e) { }
            }
        });
    }

    // Initialize Mention Autocomplete
    setupMentionAutocomplete();
}

// ───────────────────── Stepper Control ─────────────────────
window.adjustLimit = function (id, delta) {
    const input = document.getElementById(id);
    if (!input) return;
    let val = parseInt(input.value || 3) + delta;
    if (val < 1) val = 1;
    if (val > 100) val = 100;
    input.value = val;
};

// ───────────────────── Guild Management ─────────────────────
async function loadGuilds() {
    try {
        const resp = await fetch('/api/guilds');
        const guilds = await resp.json();
        guildList.innerHTML = '';
        guilds.forEach(g => {
            const item = document.createElement('div');
            item.className = 'dropdown-item';
            const iconHtml = g.icon ? `<img src="${g.icon}" alt="">` : g.name.charAt(0).toUpperCase();
            item.innerHTML = `<div class="guild-icon">${iconHtml}</div><span>${g.name}</span>`;
            item.addEventListener('click', () => selectGuild(g));
            guildList.appendChild(item);
        });

        // Automatically select first guild if none active
        if (guilds.length > 0 && !currentGuildId) {
            selectGuild(guilds[0]);
        }
    } catch (e) { }
}

async function selectGuild(guild) {
    currentGuildId = guild.id;
    guildNameDisplay.textContent = guild.name;
    guildIconSmall.innerHTML = guild.icon ? `<img src="${guild.icon}" alt="">` : guild.name.charAt(0).toUpperCase();
    guildDropdown.classList.remove('open');

    emptyState.style.display = 'none';

    // Show active tab
    const activeTab = document.querySelector('.nav-item.active').dataset.tab;
    tabContents.forEach(c => c.style.display = 'none');
    const target = document.getElementById(activeTab);
    if (target) target.style.display = 'block';

    if (breadcrumbCurrent && tabTitles[activeTab]) {
        breadcrumbCurrent.textContent = tabTitles[activeTab];
    }

    const topSaveBtn = document.getElementById('topSaveSecurityBtn');
    if (topSaveBtn) {
        topSaveBtn.style.display = activeTab === 'antinukeSection' ? 'inline-flex' : 'none';
    }

    await loadBotProfile();
    await loadCoreData();
    loadDataForActiveTab();
}

async function loadCoreData() {
    try {
        const [mResp, cResp, eResp, rResp, catResp] = await Promise.all([
            fetch(`/api/guild/${currentGuildId}/members`),
            fetch(`/api/guild/${currentGuildId}/channels`),
            fetch(`/api/guild/${currentGuildId}/emojis`),
            fetch(`/api/guild/${currentGuildId}/roles`),
            fetch(`/api/guild/${currentGuildId}/categories`)
        ]);
        currentGuildMembers = await mResp.json();
        currentGuildChannels = await cResp.json();
        currentServerEmojis = await eResp.json();
        currentGuildRoles = await rResp.json();
        currentGuildCategories = await catResp.json();

        currentGuildMembers.sort((a, b) => a.username.localeCompare(b.username));
        currentGuildChannels.sort((a, b) => a.name.localeCompare(b.name));

        // Update Emoji Counter Badge & Grid
        if (emojiCountBadge) {
            emojiCountBadge.textContent = currentServerEmojis.length;
        }
        renderEmojiGrid();
        syncAllRichEmojiEditors();

        // Populate Members Selects
        const prevWhitelist = document.getElementById('whitelistSelect') ? document.getElementById('whitelistSelect').value : '';
        const prevAbuseWhitelist = document.getElementById('abuseWhitelistSelect') ? document.getElementById('abuseWhitelistSelect').value : '';
        const memHtml = '<option value="">Select a member...</option>' +
            currentGuildMembers.map(m => `<option value="${m.id}">${escapeHtml(m.username)} (${m.id})</option>`).join('');
        document.getElementById('whitelistSelect').innerHTML = memHtml;
        document.getElementById('abuseWhitelistSelect').innerHTML = memHtml;
        setTimeout(initCustomSelects, 100);
        if (prevWhitelist) document.getElementById('whitelistSelect').value = prevWhitelist;
        if (prevAbuseWhitelist) document.getElementById('abuseWhitelistSelect').value = prevAbuseWhitelist;

        // Populate Channels Selects
        const chanHtml = '<option value="">Select a channel...</option>' +
            currentGuildChannels.map(c => `<option value="${c.id}"># ${escapeHtml(c.name)}</option>`).join('');
        const prevLevelChan = document.getElementById('levelChannelSelect') ? document.getElementById('levelChannelSelect').value : '';
        const prevAnnDest = document.getElementById('annDestChannelSelect') ? document.getElementById('annDestChannelSelect').value : '';
        const prevAnnCompose = document.getElementById('annComposeChannelSelect') ? document.getElementById('annComposeChannelSelect').value : '';
        const chanHtml2 = '<option value="">Disabled (Silent Leveling)</option>' +
            currentGuildChannels.map(c => `<option value="${c.id}"># ${escapeHtml(c.name)}</option>`).join('');

        document.getElementById('privacyChannelSelect').innerHTML = chanHtml;
        document.getElementById('levelChannelSelect').innerHTML = chanHtml2;
        if (prevLevelChan) {
            document.getElementById('levelChannelSelect').value = prevLevelChan;
        }

        const testChanSelect = document.getElementById('testChannelSelect');
        const prevTestChan = testChanSelect ? testChanSelect.value : '';
        if (testChanSelect) {
            testChanSelect.innerHTML = '<option value="">Select test destination channel...</option>' +
                currentGuildChannels.map(c => `<option value="${c.id}"># ${escapeHtml(c.name)}</option>`).join('');
            if (prevTestChan) testChanSelect.value = prevTestChan;
        }

        const rrChanSelect = document.getElementById('rrChannelSelect');
        const prevRrChan = rrChanSelect ? rrChanSelect.value : '';
        if (rrChanSelect) {
            rrChanSelect.innerHTML = '<option value="">Select a channel to post panel...</option>' +
                currentGuildChannels.map(c => `<option value="${c.id}"># ${escapeHtml(c.name)}</option>`).join('');
            if (prevRrChan) rrChanSelect.value = prevRrChan;
        }

        const annDestSelect = document.getElementById('annDestChannelSelect');
        if (annDestSelect) {
            annDestSelect.innerHTML = '<option value="">Select official announcement channel...</option>' +
                currentGuildChannels.map(c => `<option value="${c.id}"># ${escapeHtml(c.name)}</option>`).join('');
            if (configuredAnnChannelId) {
                annDestSelect.value = configuredAnnChannelId;
            } else if (prevAnnDest) {
                annDestSelect.value = prevAnnDest;
            }
        }
        
        // Ticket dropdowns
        const catHtml = '<option value="">Select a Category...</option>' + 
            currentGuildCategories.map(c => `<option value="${c.id}">${escapeHtml(c.name)}</option>`).join('');
            
        const roleHtml = '<option value="">No specific role</option>' + 
            currentGuildRoles.map(r => `<option value="${r.id}">${escapeHtml(r.name)}</option>`).join('');

        const ticketPanelChanSelect = document.getElementById('ticketPanelChannelSelect');
        const prevTicketPanelChan = ticketPanelChanSelect ? ticketPanelChanSelect.value : '';
        if (ticketPanelChanSelect) {
            ticketPanelChanSelect.innerHTML = chanHtml;
            if (prevTicketPanelChan) ticketPanelChanSelect.value = prevTicketPanelChan;
        }

        const ticketCatSelect = document.getElementById('ticketCategorySelect');
        const prevTicketCat = ticketCatSelect ? ticketCatSelect.value : '';
        if (ticketCatSelect) {
            ticketCatSelect.innerHTML = catHtml;
            if (prevTicketCat) ticketCatSelect.value = prevTicketCat;
        }

        const ticketTransChanSelect = document.getElementById('ticketTranscriptChannelSelect');
        const prevTicketTransChan = ticketTransChanSelect ? ticketTransChanSelect.value : '';
        if (ticketTransChanSelect) {
            ticketTransChanSelect.innerHTML = '<option value="">No specific channel (use category or audit logs)</option>' + 
                currentGuildChannels.map(c => `<option value="${c.id}"># ${escapeHtml(c.name)}</option>`).join('');
            if (prevTicketTransChan) ticketTransChanSelect.value = prevTicketTransChan;
        }

        const ticketTransCatSelect = document.getElementById('ticketTranscriptCategorySelect');
        const prevTicketTransCat = ticketTransCatSelect ? ticketTransCatSelect.value : '';
        if (ticketTransCatSelect) {
            ticketTransCatSelect.innerHTML = '<option value="">No specific category (default logs)</option>' + 
                currentGuildCategories.map(c => `<option value="${c.id}">${escapeHtml(c.name)}</option>`).join('');
            if (prevTicketTransCat) ticketTransCatSelect.value = prevTicketTransCat;
        }

        const ticketRoleSelect = document.getElementById('ticketRoleSelect');
        const prevTicketRole = ticketRoleSelect ? ticketRoleSelect.value : '';
        if (ticketRoleSelect) {
            ticketRoleSelect.innerHTML = roleHtml;
            if (prevTicketRole) ticketRoleSelect.value = prevTicketRole;
        }

        const annComposeSelect = document.getElementById('annComposeChannelSelect');
        if (annComposeSelect) {
            annComposeSelect.innerHTML = '<option value="">Use Configured Channel (Default)</option>' +
                currentGuildChannels.map(c => `<option value="${c.id}"># ${escapeHtml(c.name)}</option>`).join('');
            if (prevAnnCompose) {
                annComposeSelect.value = prevAnnCompose;
            }
        }

        // Initialize default Reaction Role rows if empty
        if (rrMappings.length === 0) {
            addRrMappingRow('🎉', '');
            addRrMappingRow('🔔', '');
        } else {
            refreshAllRrRoleSelects();
        }

        updateRrEmbedPreview();
        updateAnnPreview();
        updateTicketPreview();
        loadPrivacySettings();

        // Populate Auto Mentions selects
        const arMemSelect = document.getElementById('autoReactMemberSelect');
        const autoRespMemSelect = document.getElementById('autoRespMemberSelect');
        const memOpts = '<option value="">Select a member...</option>' + 
            currentGuildMembers.map(m => `<option value="${m.id}">${escapeHtml(m.username)} (${m.id})</option>`).join('');
        if (arMemSelect) arMemSelect.innerHTML = memOpts;
        if (autoRespMemSelect) autoRespMemSelect.innerHTML = memOpts;

        const autoRespIgnChanSelect = document.getElementById('autoRespIgnoreChannelSelect');
        if (autoRespIgnChanSelect) {
            autoRespIgnChanSelect.innerHTML = '<option value="">Select a channel to ignore...</option>' +
                currentGuildChannels.map(c => `<option value="${c.id}"># ${escapeHtml(c.name)}</option>`).join('');
        }

        const fwChanSelect = document.getElementById('firstWelcomeChannelSelect');
        if (fwChanSelect) {
            const prevFwVal = fwChanSelect.value;
            fwChanSelect.innerHTML = '<option value="">Any Chat Channel (Anywhere they type first)</option>' +
                currentGuildChannels.map(c => `<option value="${c.id}"># ${escapeHtml(c.name)}</option>`).join('');
            if (prevFwVal) fwChanSelect.value = prevFwVal;
        }

        initCustomSelects();
    } catch (e) { }
}

async function loadDataForActiveTab() {
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
    else if (activeTab === 'responsesSection') await loadResponsesSettings();
    else if (activeTab === 'automationsSection') await loadAutomationsSettings();
    else if (activeTab === 'firstWelcomeSection') await loadFirstWelcomeSettings();
    else if (activeTab === 'afkSection') await loadAfkSettings();
}

// ───────────────────── Emoji Picker Logic ─────────────────────
function openEmojiPicker(triggerEl, callback) {
    emojiSelectCallback = callback;
    if (!emojiPopover) return;

    const rect = triggerEl.getBoundingClientRect();
    const popoverWidth = 360;
    const popoverHeight = 320;

    let left = rect.left;
    if (left + popoverWidth > window.innerWidth - 20) {
        left = window.innerWidth - popoverWidth - 20;
    }

    let top = rect.bottom + 8;
    if (top + popoverHeight > window.innerHeight - 20) {
        top = rect.top - popoverHeight - 8;
    }

    emojiPopover.style.position = 'fixed';
    emojiPopover.style.left = `${Math.max(10, Math.round(left))}px`;
    emojiPopover.style.top = `${Math.max(10, Math.round(top))}px`;
    emojiPopover.style.bottom = 'auto';
    emojiPopover.style.right = 'auto';
    emojiPopover.classList.add('open');

    if (emojiSearchInput) {
        emojiSearchInput.value = '';
        emojiSearchQuery = '';
        renderEmojiGrid();
        emojiSearchInput.focus();
    }
}

function closeEmojiPicker() {
    if (emojiPopover) emojiPopover.classList.remove('open');
}

function renderEmojiGrid() {
    if (!serverEmojiGrid) return;
    serverEmojiGrid.innerHTML = '';

    let itemsToDisplay = [];
    const query = (emojiSearchQuery || '').trim().toLowerCase();

    if (currentEmojiTab === 'standard') {
        let std = STANDARD_EMOJI_LIBRARY;
        if (query) {
            std = std.filter(e => e.name.toLowerCase().includes(query) || e.char.includes(query));
        }
        itemsToDisplay = std.map(em => ({ type: 'standard', char: em.char, title: em.name }));
    } else {
        // Filter Server Custom Emojis
        let filtered = currentServerEmojis || [];
        if (currentEmojiTab === 'animated') {
            filtered = filtered.filter(e => e.animated);
        } else if (currentEmojiTab === 'static') {
            filtered = filtered.filter(e => !e.animated);
        }

        if (query) {
            filtered = filtered.filter(e => e.name.toLowerCase().includes(query));
        }

        itemsToDisplay = filtered.map(e => ({ type: 'custom', ...e }));

        // Include matching standard emojis if on 'all' tab
        if (currentEmojiTab === 'all') {
            let std = STANDARD_EMOJI_LIBRARY;
            if (query) {
                std = std.filter(e => e.name.toLowerCase().includes(query) || e.char.includes(query));
            }
            std.forEach(em => {
                itemsToDisplay.push({ type: 'standard', char: em.char, title: em.name });
            });
        }
    }

    if (itemsToDisplay.length === 0) {
        serverEmojiGrid.innerHTML = `<div class="emoji-empty-msg">No matching emojis found.</div>`;
        return;
    }

    itemsToDisplay.forEach(item => {
        const btn = document.createElement('button');
        btn.type = 'button';
        btn.className = 'emoji-item';

        if (item.type === 'custom') {
            btn.title = `:${item.name}: (${item.animated ? 'Animated GIF' : 'Static'})`;
            btn.innerHTML = `<img src="${item.url}" alt="${item.name}">`;
            btn.addEventListener('click', () => {
                if (emojiSelectCallback) {
                    const code = item.code || (item.animated ? `<a:${item.name}:${item.id}>` : `<:${item.name}:${item.id}>`);
                    emojiSelectCallback(code);
                }
                closeEmojiPicker();
            });
        } else {
            btn.title = `${item.char} ${item.title || ''}`.trim();
            btn.textContent = item.char;
            btn.addEventListener('click', () => {
                if (emojiSelectCallback) {
                    emojiSelectCallback(item.char);
                }
                closeEmojiPicker();
            });
        }

        serverEmojiGrid.appendChild(btn);
    });
}

// ───────────────────── Rich Visual Emoji Editor Engine (Ticket King Style) ─────────────────────

function sanitizeRawMarkdown(raw) {
    if (!raw) return '';
    let s = String(raw);
    s = s.replace(/<img[^>]*data-emoji="([^"]+)"[^>]*>/gi, '$1');
    s = s.replace(/<img[^>]*src="https:\/\/cdn\.discordapp\.com\/emojis\/([0-9]+)\.(png|gif)[^"]*"[^>]*>/gi, '<:emoji:$1>');
    s = s.replace(/\s*[0-9]+>"\s*src="https:\/\/cdn\.discordapp\.com\/emojis\/[0-9]+\.(png|gif)[^"]*"\s*alt="[^"]*"\s*title="[^"]*"\s*contenteditable="false">\s*/gi, ' ');
    return s;
}

function rawMarkdownToRichHtml(raw) {
    if (!raw) return '';
    let s = sanitizeRawMarkdown(raw);
    s = s.replace(/&/g, '&amp;')
        .replace(/</g, '&lt;')
        .replace(/>/g, '&gt;');

    // Single unified regex to prevent recursive replacement inside attributes
    const emojiRegex = /(&lt;a:([a-zA-Z0-9_]+):([0-9]+)&gt;|&lt;:([a-zA-Z0-9_]+):([0-9]+)&gt;|:([a-zA-Z0-9_]+):)/g;

    s = s.replace(emojiRegex, (match, full, animName, animId, staticName, staticId, colonName) => {
        if (animName && animId) {
            const code = `<a:${animName}:${animId}>`;
            const url = `https://cdn.discordapp.com/emojis/${animId}.gif?size=48&quality=lossless`;
            return `<img class="editor-inline-emoji animated" data-emoji="${code}" src="${url}" alt="${animName}" title=":${animName}:" contenteditable="false">`;
        }
        if (staticName && staticId) {
            const code = `<:${staticName}:${staticId}>`;
            const url = `https://cdn.discordapp.com/emojis/${staticId}.png?size=48`;
            return `<img class="editor-inline-emoji" data-emoji="${code}" src="${url}" alt="${staticName}" title=":${staticName}:" contenteditable="false">`;
        }
        if (colonName && typeof currentServerEmojis !== 'undefined' && currentServerEmojis && currentServerEmojis.length) {
            const found = currentServerEmojis.find(e => e.name.toLowerCase() === colonName.toLowerCase());
            if (found) {
                const code = found.code || (found.animated ? `<a:${found.name}:${found.id}>` : `<:${found.name}:${found.id}>`);
                const clazz = found.animated ? 'editor-inline-emoji animated' : 'editor-inline-emoji';
                return `<img class="${clazz}" data-emoji="${code}" src="${found.url}" alt="${found.name}" title=":${found.name}:" contenteditable="false">`;
            }
        }
        return match;
    });

    // Line breaks to <br>
    return s.replace(/\n/g, '<br>');
}

function richHtmlToRawMarkdown(el) {
    if (!el) return '';
    let result = '';
    function traverse(node) {
        if (node.nodeType === Node.TEXT_NODE) {
            result += node.nodeValue;
        } else if (node.nodeType === Node.ELEMENT_NODE) {
            if (node.tagName === 'IMG') {
                const dataEmoji = node.getAttribute('data-emoji');
                if (dataEmoji) {
                    result += dataEmoji;
                } else {
                    const src = node.getAttribute('src') || '';
                    const m = src.match(/cdn\.discordapp\.com\/emojis\/([0-9]+)\.(png|gif)/);
                    if (m) {
                        result += `<:emoji:${m[1]}>`;
                    }
                }
            } else if (node.tagName === 'BR') {
                result += '\n';
            } else if (node.tagName === 'DIV' || node.tagName === 'P') {
                if (result.length > 0 && !result.endsWith('\n')) {
                    result += '\n';
                }
                for (const child of node.childNodes) traverse(child);
            } else {
                for (const child of node.childNodes) traverse(child);
            }
        }
    }
    for (const child of el.childNodes) traverse(child);
    return sanitizeRawMarkdown(result);
}

function insertEmojiOrTextIntoRichEditor(richEl, val) {
    if (!richEl) return;
    richEl.focus();
    const sel = window.getSelection();
    let range;
    if (sel && sel.rangeCount && richEl.contains(sel.anchorNode)) {
        range = sel.getRangeAt(0);
    } else {
        range = document.createRange();
        range.selectNodeContents(richEl);
        range.collapse(false);
    }

    range.deleteContents();

    let animMatch = val.match(/^<a:([a-zA-Z0-9_]+):([0-9]+)>$/);
    let staticMatch = val.match(/^<:([a-zA-Z0-9_]+):([0-9]+)>$/);

    if (!animMatch && !staticMatch) {
        const colonMatch = val.match(/^:([a-zA-Z0-9_]+):$/);
        if (colonMatch && typeof currentServerEmojis !== 'undefined' && currentServerEmojis) {
            const found = currentServerEmojis.find(e => e.name.toLowerCase() === colonMatch[1].toLowerCase());
            if (found) {
                if (found.animated) {
                    animMatch = [val, found.name, found.id];
                } else {
                    staticMatch = [val, found.name, found.id];
                }
            }
        }
    }

    if (animMatch || staticMatch) {
        const isAnim = Boolean(animMatch);
        const name = isAnim ? animMatch[1] : staticMatch[1];
        const id = isAnim ? animMatch[2] : staticMatch[2];
        const emojiCode = isAnim ? `<a:${name}:${id}>` : `<:${name}:${id}>`;
        const url = `https://cdn.discordapp.com/emojis/${id}.${isAnim ? 'gif' : 'png'}?size=48&quality=lossless`;
        
        const img = document.createElement('img');
        img.className = `editor-inline-emoji${isAnim ? ' animated' : ''}`;
        img.setAttribute('data-emoji', emojiCode);
        img.src = url;
        img.alt = emojiCode;
        img.title = `:${name}:`;
        img.contentEditable = 'false';
        
        range.insertNode(img);

        const space = document.createTextNode(' ');
        if (img.nextSibling) {
            img.parentNode.insertBefore(space, img.nextSibling);
        } else {
            img.parentNode.appendChild(space);
        }
        range.setStartAfter(space);
        range.setEndAfter(space);
    } else {
        const textNode = document.createTextNode(val + ' ');
        range.insertNode(textNode);
        range.setStartAfter(textNode);
        range.setEndAfter(textNode);
    }

    sel.removeAllRanges();
    sel.addRange(range);
    richEl.dispatchEvent(new Event('input', { bubbles: true }));
}

function attachRichEmojiEditor(targetId, isSingleLine = false) {
    const targetEl = document.getElementById(targetId);
    if (!targetEl) return null;
    if (targetEl.dataset.richEditorReady) {
        return document.getElementById(targetId + '_rich');
    }
    targetEl.dataset.richEditorReady = "true";
    targetEl.style.display = 'none';

    const richEl = document.createElement('div');
    richEl.id = targetId + '_rich';
    richEl.className = 'rich-emoji-editor' + (isSingleLine ? ' single-line' : '');
    richEl.contentEditable = 'true';
    richEl.spellcheck = false;

    if (targetEl.placeholder) {
        richEl.setAttribute('data-placeholder', targetEl.placeholder);
    }

    targetEl.parentNode.insertBefore(richEl, targetEl.nextSibling);

    // Initial render
    richEl.innerHTML = rawMarkdownToRichHtml(targetEl.value || '');

    if (isSingleLine) {
        richEl.addEventListener('keydown', (e) => {
            if (e.key === 'Enter') {
                e.preventDefault();
                richEl.blur();
            }
        });
    }

    richEl.addEventListener('input', () => {
        const raw = richHtmlToRawMarkdown(richEl);
        targetEl.value = raw;
        targetEl.dispatchEvent(new Event('input', { bubbles: true }));
    });

    richEl.addEventListener('paste', (e) => {
        e.preventDefault();
        const text = (e.clipboardData || window.clipboardData).getData('text');
        if (!text) return;
        const html = rawMarkdownToRichHtml(text);
        document.execCommand('insertHTML', false, html);
        const raw = richHtmlToRawMarkdown(richEl);
        targetEl.value = raw;
        targetEl.dispatchEvent(new Event('input', { bubbles: true }));
    });

    richEl.addEventListener('blur', () => {
        const raw = richHtmlToRawMarkdown(richEl);
        richEl.innerHTML = rawMarkdownToRichHtml(raw);
    });

    targetEl._syncToRich = function() {
        richEl.innerHTML = rawMarkdownToRichHtml(targetEl.value || '');
    };

    return richEl;
}

function initAllRichEmojiEditors() {
    attachRichEmojiEditor('ticketDescInput');
    attachRichEmojiEditor('ticketTitleInput', true);
    [1, 2, 3, 4].forEach(n => attachRichEmojiEditor('ticketBtn' + n, true));
    attachRichEmojiEditor('levelMessageInput');
    attachRichEmojiEditor('rrDescInput');
    attachRichEmojiEditor('rrTitleInput', true);
    attachRichEmojiEditor('annContentInput');
    attachRichEmojiEditor('annTitleInput', true);
}

function syncAllRichEmojiEditors() {
    const ids = [
        'ticketDescInput', 'ticketTitleInput',
        'ticketBtn1', 'ticketBtn2', 'ticketBtn3', 'ticketBtn4',
        'levelMessageInput',
        'rrDescInput', 'rrTitleInput',
        'annContentInput', 'annTitleInput'
    ];
    ids.forEach(id => {
        const el = document.getElementById(id);
        if (el && typeof el._syncToRich === 'function') {
            el._syncToRich();
        }
    });
}

// ───────────────────── Anti-Nuke Logic ─────────────────────
function updateAntinukeBadge(isActive) {
    const badge = document.getElementById('antinukeStatusBadge');
    const banner = document.getElementById('masterPausedBanner');
    const protectedContainer = document.getElementById('secProtectedControls');
    if (badge) {
        if (isActive) {
            badge.className = 'status-pill active';
            badge.innerHTML = '<span class="status-pulse"></span> Active Protection';
        } else {
            badge.className = 'status-pill inactive';
            badge.innerHTML = '<span class="status-pulse-off"></span> Paused';
        }
    }
    if (banner) {
        banner.style.display = isActive ? 'none' : 'flex';
    }
    if (protectedContainer) {
        protectedContainer.classList.toggle('sec-master-paused', !isActive);
    }
}


async function toggleAntinuke(e) {
    const isActive = e.target.checked;
    updateAntinukeBadge(isActive);
    try {
        await fetch(`/api/guild/${currentGuildId}/antinuke/toggle`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ active: isActive })
        });
        showToast(isActive ? "🛡️ Master Anti-Nuke Engine Activated" : "⚠️ Master Anti-Nuke Engine Paused (All defenses halted)");
    } catch (err) {
        showToast("❌ Failed to toggle Anti-Nuke state");
    }
}


// ───────────────────── Leveling Logic & Real-Time Discord Simulation ─────────────────────
async function loadLevelingSettings() {
    try {
        const resp = await fetch(`/api/guild/${currentGuildId}/leveling`);
        const data = await resp.json();
        const chanSelect = document.getElementById('levelChannelSelect');
        const targetVal = (data.channel !== undefined && data.channel !== null) ? String(data.channel) : "";
        if (chanSelect) {
            chanSelect.value = targetVal;
        }
        const msgInput = document.getElementById('levelMessageInput');
        if (msgInput) {
            msgInput.value = data.message || "";
        }
        const testChan = document.getElementById('testChannelSelect');
        if (testChan && !testChan.value && targetVal) {
            testChan.value = targetVal;
        }

        // Mode restoration
        const mode = data.mode || "both";
        const modeInput = document.getElementById('levelModeInput');
        if (modeInput) modeInput.value = mode;
        document.querySelectorAll('#levelModeGroup .mode-segment-btn').forEach(btn => {
            btn.classList.toggle('active', btn.dataset.mode === mode);
        });

        syncAllRichEmojiEditors();
        updateLevelPreview();
    } catch (err) {
        console.error("Error loading leveling settings:", err);
    }
}

async function saveLeveling() {
    const sel = document.getElementById('levelChannelSelect');
    const chanVal = sel ? sel.value : "";
    const msgVal = document.getElementById('levelMessageInput').value;
    const modeVal = document.getElementById('levelModeInput') ? document.getElementById('levelModeInput').value : "both";
    const body = {
        channel: chanVal,
        message: msgVal,
        mode: modeVal
    };
    try {
        const resp = await fetch(`/api/guild/${currentGuildId}/leveling/update`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(body)
        });
        const res = await resp.json();
        if (res.success) {
            showToast("✅ Leveling settings saved!");
        } else {
            showToast(`❌ ${res.error || 'Failed to save leveling settings'}`);
        }
    } catch (e) {
        showToast("❌ Network error saving leveling settings");
    }
}

/**
 * Robust line-by-line Discord Markdown Parser.
 * Ensures headers (#, ##, ###) and subtext (-#) strictly apply to their specific line
 * without cascading or bleeding into subsequent lines!
 */
function renderDiscordMarkdown(rawText) {
    if (!rawText) return "";

    // Normalize newlines to \n and split strictly by line
    const lines = rawText.replace(/\r\n/g, '\n').replace(/\r/g, '\n').split('\n');
    let inMultiQuote = false;
    let htmlOutput = [];

    for (let i = 0; i < lines.length; i++) {
        let line = lines[i];

        // Multi-line quote >>> detection
        if (line.startsWith('>>> ')) {
            inMultiQuote = true;
            line = line.substring(4);
        } else if (line === '>>>') {
            inMultiQuote = true;
            line = '';
        }

        // Clean HTML escape for security
        let processed = escapeHtml(line);

        // 1. Dynamic Variables
        processed = processed.replace(/\{user\}/g, '<span class="discord-mention">@User</span>');
        processed = processed.replace(/\{level\}/g, '<span class="discord-level-badge">5</span>');

        // 2. Custom & Server Discord Emojis (Unified single pass to prevent nested attribute corruption)
        const emojiUnifiedRegex = /(?:&lt;|<)a:([a-zA-Z0-9_]+):([0-9]+)(?:&gt;|>)|(?:&lt;|<):([a-zA-Z0-9_]+):([0-9]+)(?:&gt;|>)|:([a-zA-Z0-9_]+):/g;
        processed = processed.replace(emojiUnifiedRegex, (match, animName, animId, staticName, staticId, colonName) => {
            if (animName && animId) {
                return `<img class="discord-custom-emoji animated" src="https://cdn.discordapp.com/emojis/${animId}.gif?size=48&quality=lossless" alt="${animName}" title="${animName}">`;
            }
            if (staticName && staticId) {
                return `<img class="discord-custom-emoji" src="https://cdn.discordapp.com/emojis/${staticId}.png?size=48" alt="${staticName}" title="${staticName}">`;
            }
            if (colonName && typeof currentServerEmojis !== 'undefined' && Array.isArray(currentServerEmojis) && currentServerEmojis.length) {
                const found = currentServerEmojis.find(e => e.name && e.name.toLowerCase() === colonName.toLowerCase());
                if (found) {
                    const clazz = found.animated ? 'discord-custom-emoji animated' : 'discord-custom-emoji';
                    const ext = found.animated ? 'gif?size=48&quality=lossless' : 'png?size=48';
                    const url = found.url || `https://cdn.discordapp.com/emojis/${found.id}.${ext}`;
                    return `<img class="${clazz}" src="${url}" alt="${found.name}" title="${found.name}">`;
                }
            }
            return match;
        });

        // 3. Mentions
        processed = processed.replace(/&lt;@!?([0-9]+)&gt;/g, (match, uid) => {
            let name = 'User';
            if (typeof currentGuildMembers !== 'undefined' && currentGuildMembers.length) {
                const found = currentGuildMembers.find(m => m.id === uid);
                if (found) name = found.username;
            }
            return `<span class="discord-mention">@${escapeHtml(name)}</span>`;
        });
        processed = processed.replace(/&lt;#([0-9]+)&gt;/g, (match, cid) => {
            let name = 'channel';
            if (typeof currentGuildChannels !== 'undefined' && currentGuildChannels.length) {
                const found = currentGuildChannels.find(c => c.id === cid);
                if (found) name = found.name;
            }
            return `<span class="discord-mention">#${escapeHtml(name)}</span>`;
        });
        processed = processed.replace(/&lt;@&amp;([0-9]+)&gt;/g, (match, rid) => {
            let name = 'Role';
            if (typeof currentGuildRoles !== 'undefined' && currentGuildRoles.length) {
                const found = currentGuildRoles.find(r => r.id === rid);
                if (found) name = found.name;
            }
            return `<span class="discord-mention">@${escapeHtml(name)}</span>`;
        });
        processed = processed.replace(/@everyone/g, '<span class="discord-mention">@everyone</span>');
        processed = processed.replace(/@here/g, '<span class="discord-mention">@here</span>');

        // 4. Inline Code: `code`
        processed = processed.replace(/`([^`]+)`/g, '<code class="discord-inline-code">$1</code>');

        // 5. In-line text formatting
        // Bold Italic: ***text***
        processed = processed.replace(/\*\*\*(.*?)\*\*\*/g, '<strong><em>$1</em></strong>');
        // Bold: **text**
        processed = processed.replace(/\*\*(.*?)\*\*/g, '<strong>$1</strong>');
        // Underline: __text__
        processed = processed.replace(/__(.*?)__/g, '<u>$1</u>');
        // Italic: *text* or _text_
        processed = processed.replace(/\*(.*?)\*/g, '<em>$1</em>');
        processed = processed.replace(/(?<!\w)_(.*?)_(?!\w)/g, '<em>$1</em>');
        // Strikethrough: ~~text~~
        processed = processed.replace(/~~(.*?)~~/g, '<s>$1</s>');
        // Spoiler: ||text||
        processed = processed.replace(/\|\|(.*?)\|\|/g, '<span class="discord-spoiler" onclick="this.classList.toggle(\'revealed\')">$1</span>');

        // 6. Block-Level Line Rendering (APPLIES TO THIS LINE ONLY!)
        if (inMultiQuote) {
            htmlOutput.push(`<div class="discord-quote-line">${processed || '&nbsp;'}</div>`);
        } else if (line.startsWith('# ')) {
            // # Heading 1 (Strictly this line only!)
            let content = processed.replace(/^#\s+/, '');
            htmlOutput.push(`<div class="discord-h1">${content || '&nbsp;'}</div>`);
        } else if (line.startsWith('## ')) {
            // ## Heading 2 (Strictly this line only!)
            let content = processed.replace(/^##\s+/, '');
            htmlOutput.push(`<div class="discord-h2">${content || '&nbsp;'}</div>`);
        } else if (line.startsWith('### ')) {
            // ### Heading 3 (Strictly this line only!)
            let content = processed.replace(/^###\s+/, '');
            htmlOutput.push(`<div class="discord-h3">${content || '&nbsp;'}</div>`);
        } else if (line.startsWith('-# ')) {
            // -# Subtext (Strictly this line only!)
            let content = processed.replace(/^-#\s+/, '');
            htmlOutput.push(`<div class="discord-subtext">${content || '&nbsp;'}</div>`);
        } else if (line.startsWith('&gt; ') || line.startsWith('> ')) {
            // > Single-line Quote (Strictly this line only!)
            let content = processed.replace(/^(&gt;|>)\s+/, '');
            htmlOutput.push(`<div class="discord-quote-line">${content || '&nbsp;'}</div>`);
        } else {
            // Standard Discord text line
            htmlOutput.push(`<div class="discord-line">${processed || '&nbsp;'}</div>`);
        }
    }

    return htmlOutput.join('');
}

function updateLevelPreview() {
    const input = document.getElementById('levelMessageInput');
    const preview = document.getElementById('levelPreviewBody');
    const mode = document.getElementById('levelModeInput') ? document.getElementById('levelModeInput').value : 'both';
    const textInputWrap = document.getElementById('levelTextInputWrapper');
    const cardPreview = document.getElementById('levelCardPreview');

    if (textInputWrap) textInputWrap.style.display = (mode === 'image') ? 'none' : 'block';
    if (preview) preview.style.display = (mode === 'image') ? 'none' : 'block';
    if (cardPreview) cardPreview.style.display = (mode === 'text') ? 'none' : 'block';

    if (!input || !preview) return;

    const raw = input.value || "🎉 LEVEL UP!\n**{user}** just advanced to **Level {level}**!";
    preview.innerHTML = renderDiscordMarkdown(raw);
    if (currentBotAvatar) {
        updateBotAvatars(currentBotAvatar);
    }
}

window.insertVariable = function (text) {
    const richEl = document.getElementById('levelMessageInput_rich');
    if (richEl) {
        insertEmojiOrTextIntoRichEditor(richEl, text);
        return;
    }
    const input = document.getElementById('levelMessageInput');
    if (!input) return;
    const start = input.selectionStart || input.value.length;
    const end = input.selectionEnd || input.value.length;
    input.value = input.value.substring(0, start) + text + input.value.substring(end);
    input.focus();
    input.selectionStart = input.selectionEnd = start + text.length;
    updateLevelPreview();
};

function escapeHtml(text) {
    if (!text) return '';
    return text
        .replace(/&/g, '&amp;')
        .replace(/</g, '&lt;')
        .replace(/>/g, '&gt;')
        .replace(/"/g, '&quot;')
        .replace(/'/g, '&#039;');
}

// ───────────────────── Anti-Abuse Logic ─────────────────────
let bannedWords = [];
async function loadAntiabuseSettings() {
    const resp = await fetch(`/api/guild/${currentGuildId}/antiabuse`);
    const data = await resp.json();
    bannedWords = data.words || [];
    renderTags('bannedWordsList', bannedWords, (w) => removeBannedWord(w));
    renderWhitelist('abuseWhitelistList', data.whitelist, 'antiabuse');
}

async function addBannedWord(word) {
    word = word.trim().toLowerCase();
    if (!word || bannedWords.includes(word)) return;
    bannedWords.push(word);
    document.getElementById('bannedWordInput').value = '';
    await fetch(`/api/guild/${currentGuildId}/antiabuse/words`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ words: bannedWords })
    });
    renderTags('bannedWordsList', bannedWords, (w) => removeBannedWord(w));
    showToast("🚫 Word added to blacklist");
}

async function removeBannedWord(word) {
    bannedWords = bannedWords.filter(w => w !== word);
    await fetch(`/api/guild/${currentGuildId}/antiabuse/words`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ words: bannedWords })
    });
    renderTags('bannedWordsList', bannedWords, (w) => removeBannedWord(w));
}

// ───────────────────── Privacy Logic ─────────────────────
let ignoredChannels = [];
let privacyChannelsList = [];
let privacyCategoriesList = [];

async function loadPrivacySettings() {
    try {
        const resp = await fetch(`/api/guild/${currentGuildId}/privacy`);
        const data = await resp.json();
        ignoredChannels = data.ignored || [];
        privacyChannelsList = data.channels || [];
        privacyCategoriesList = data.categories || [];

        // Update Lockdown Phase UI
        updateLockdownPhaseUI(Boolean(data.lockdown_active));

        // 1. Render tags for exempt channels
        renderTags('privacyIgnoredList', ignoredChannels.map(id => {
            const c = currentGuildChannels.find(ch => ch.id == id);
            return c ? `#${escapeHtml(c.name)}` : id;
        }), (name) => removePrivacyIgnored(name));

        // 2. Populate privacyChannelSelect (for exempting)
        const exemptSelect = document.getElementById('privacyChannelSelect');
        if (exemptSelect) {
            exemptSelect.innerHTML = '<option value="">Select a channel to exempt...</option>' +
                currentGuildChannels.filter(c => !ignoredChannels.includes(c.id)).map(c => `<option value="${c.id}"># ${escapeHtml(c.name)}</option>`).join('');
        }

        // 3. Populate Individual Channel Privacy Selects
        let publicChans = privacyChannelsList.filter(c => !c.is_private);
        let privateChans = privacyChannelsList.filter(c => c.is_private);

        if (publicChans.length === 0 && privateChans.length === 0 && currentGuildChannels.length > 0) {
            publicChans = currentGuildChannels.map(c => ({
                id: c.id,
                name: c.name,
                category: "Text Channels",
                is_private: false
            }));
        }

        const privChanSelect = document.getElementById('privChanSelect');
        if (privChanSelect) {
            if (publicChans.length > 0) {
                privChanSelect.innerHTML = '<option value="">Select public channel to lock...</option>' +
                    publicChans.map(c => `<option value="${c.id}"># ${escapeHtml(c.name)} (${escapeHtml(c.category || 'Text')})</option>`).join('');
            } else {
                privChanSelect.innerHTML = '<option value="" disabled>All channels are already private</option>';
            }
        }

        const unprivChanSelect = document.getElementById('unprivChanSelect');
        if (unprivChanSelect) {
            if (privateChans.length > 0) {
                unprivChanSelect.innerHTML = '<option value="">Select private channel to unlock...</option>' +
                    privateChans.map(c => `<option value="${c.id}">🔒 # ${escapeHtml(c.name)} (${escapeHtml(c.category || 'Text')})</option>`).join('');
            } else {
                unprivChanSelect.innerHTML = '<option value="" disabled>No private channels currently</option>';
            }
        }

        // 4. Populate Category Privacy Selects
        let publicCats = privacyCategoriesList.filter(c => !c.is_private);
        let privateCats = privacyCategoriesList.filter(c => c.is_private);

        if (publicCats.length === 0 && privateCats.length === 0 && currentGuildCategories.length > 0) {
            publicCats = currentGuildCategories.filter(c => !c.is_private);
            privateCats = currentGuildCategories.filter(c => c.is_private);
        }

        const privCatSelect = document.getElementById('privCatSelect');
        if (privCatSelect) {
            if (publicCats.length > 0) {
                privCatSelect.innerHTML = '<option value="">Select public category to lock...</option>' +
                    publicCats.map(c => `<option value="${c.id}">${escapeHtml(c.name)} (${c.channel_count || 0} channels)</option>`).join('');
            } else {
                privCatSelect.innerHTML = '<option value="" disabled>No public categories</option>';
            }
        }

        const unprivCatSelect = document.getElementById('unprivCatSelect');
        if (unprivCatSelect) {
            if (privateCats.length > 0) {
                unprivCatSelect.innerHTML = '<option value="">Select private category to unlock...</option>' +
                    privateCats.map(c => `<option value="${c.id}">🔒 ${escapeHtml(c.name)} (${c.channel_count || 0} channels)</option>`).join('');
            } else {
                unprivCatSelect.innerHTML = '<option value="" disabled>No private categories currently</option>';
            }
        }
    } catch (err) {
        console.error("Error loading privacy settings:", err);
    }
}

function updateLockdownPhaseUI(isActive) {
    const badge = document.getElementById('lockdownPhaseBadge');
    const banner = document.getElementById('lockdownAlertBanner');
    const card = document.getElementById('lockdownHeroCard');
    const unlockBtn = document.getElementById('unlockAllChannelsBtn');

    if (isActive) {
        if (badge) {
            badge.textContent = '🚨 LOCKDOWN PHASE ACTIVE';
            badge.style.background = 'rgba(239, 68, 68, 0.25)';
            badge.style.color = '#f87171';
            badge.style.borderColor = 'rgba(239, 68, 68, 0.5)';
            badge.classList.add('lockdown-active-pulse');
        }
        if (banner) banner.style.display = 'flex';
        if (card) {
            card.style.borderColor = 'rgba(239, 68, 68, 0.6)';
            card.style.boxShadow = '0 0 25px rgba(239, 68, 68, 0.2), inset 0 1px 0 rgba(255, 255, 255, 0.1)';
        }
        if (unlockBtn) {
            unlockBtn.style.boxShadow = '0 0 15px rgba(52, 211, 153, 0.35)';
            unlockBtn.style.borderColor = 'rgba(52, 211, 153, 0.6)';
            unlockBtn.style.color = '#34d399';
        }
    } else {
        if (badge) {
            badge.textContent = '🛡️ SERVER UNLOCKED (NORMAL)';
            badge.style.background = 'rgba(16, 185, 129, 0.15)';
            badge.style.color = '#34d399';
            badge.style.borderColor = 'rgba(16, 185, 129, 0.3)';
            badge.classList.remove('lockdown-active-pulse');
        }
        if (banner) banner.style.display = 'none';
        if (card) {
            card.style.borderColor = 'rgba(239, 68, 68, 0.3)';
            card.style.boxShadow = 'none';
        }
        if (unlockBtn) {
            unlockBtn.style.boxShadow = 'none';
            unlockBtn.style.borderColor = '';
            unlockBtn.style.color = '';
        }
    }
}

async function handleGlobalLockdown() {
    if (!ignoredChannels || ignoredChannels.length === 0) {
        return showToast('⚠️ You must set at least 1 Lockdown Exempt channel before locking down!');
    }
    if (!confirm("🚨 Are you sure you want to lock down the server?\n\nAll text channels will be hidden from @everyone except your exempt channels (which will become Read-Only).")) {
        return;
    }
    const btn = document.getElementById('initiateLockdownBtn');
    btn.disabled = true;
    const origHtml = btn.innerHTML;
    btn.innerHTML = `<span>⏳</span> Locking down...`;
    try {
        const resp = await fetch(`/api/guild/${currentGuildId}/privacy/lockdown`, { method: 'POST' });
        const data = await resp.json();
        if (data.success) {
            showToast(`🚨 Lockdown complete! ${data.privated} channels hidden, ${data.ignored} protected.`);
            updateLockdownPhaseUI(true);
            await loadPrivacySettings();
        } else {
            showToast(`❌ Error: ${data.error || 'Failed to initiate lockdown'}`);
        }
    } catch (e) {
        showToast("❌ Network error during lockdown");
    } finally {
        btn.disabled = false;
        btn.innerHTML = origHtml;
    }
}

async function handleUnlockAllChannels() {
    if (!confirm("🔓 Are you sure you want to unlock all channels across the entire server?")) {
        return;
    }
    const btn = document.getElementById('unlockAllChannelsBtn');
    btn.disabled = true;
    const origHtml = btn.innerHTML;
    btn.innerHTML = `<span>⏳</span> Unlocking...`;
    try {
        const resp = await fetch(`/api/guild/${currentGuildId}/privacy/unlock_all`, { method: 'POST' });
        const data = await resp.json();
        if (data.success) {
            showToast(`🔓 Server unlocked! Restored permissions for ${data.unlocked} channels.`);
            updateLockdownPhaseUI(false);
            await loadPrivacySettings();
        } else {
            showToast(`❌ Error: ${data.error || 'Failed to unlock channels'}`);
        }
    } catch (e) {
        showToast("❌ Network error during unlock all");
    } finally {
        btn.disabled = false;
        btn.innerHTML = origHtml;
    }
}

async function handlePrivChan() {
    const sel = document.getElementById('privChanSelect');
    const id = sel.value;
    if (!id) return showToast('⚠️ Select a public channel to lock');
    try {
        const resp = await fetch(`/api/guild/${currentGuildId}/privacy/channel`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ channel_id: id, action: 'private' })
        });
        const data = await resp.json();
        if (data.success) {
            showToast(`🔒 #${data.channel_name} is now hidden/private`);
            await loadPrivacySettings();
        } else {
            showToast(`❌ Error: ${data.error}`);
        }
    } catch (e) {
        showToast("❌ Network error updating channel privacy");
    }
}

async function handleUnprivChan() {
    const sel = document.getElementById('unprivChanSelect');
    const id = sel.value;
    if (!id) return showToast('⚠️ Select a private channel to unlock');
    try {
        const resp = await fetch(`/api/guild/${currentGuildId}/privacy/channel`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ channel_id: id, action: 'unprivate' })
        });
        const data = await resp.json();
        if (data.success) {
            showToast(`🔓 #${data.channel_name} is now public`);
            await loadPrivacySettings();
        } else {
            showToast(`❌ Error: ${data.error}`);
        }
    } catch (e) {
        showToast("❌ Network error updating channel privacy");
    }
}

async function handlePrivCat() {
    const sel = document.getElementById('privCatSelect');
    const id = sel.value;
    if (!id) return showToast('⚠️ Select a public category to lock');
    try {
        const resp = await fetch(`/api/guild/${currentGuildId}/privacy/category`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ category_id: id, action: 'private' })
        });
        const data = await resp.json();
        if (data.success) {
            showToast(`🔒 Locked category "${data.category_name}" (${data.count} channels)`);
            await loadPrivacySettings();
        } else {
            showToast(`❌ Error: ${data.error}`);
        }
    } catch (e) {
        showToast("❌ Network error updating category privacy");
    }
}

async function handleUnprivCat() {
    const sel = document.getElementById('unprivCatSelect');
    const id = sel.value;
    if (!id) return showToast('⚠️ Select a private category to unlock');
    try {
        const resp = await fetch(`/api/guild/${currentGuildId}/privacy/category`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ category_id: id, action: 'unprivate' })
        });
        const data = await resp.json();
        if (data.success) {
            showToast(`🔓 Unlocked category "${data.category_name}" (${data.count} channels)`);
            await loadPrivacySettings();
        } else {
            showToast(`❌ Error: ${data.error}`);
        }
    } catch (e) {
        showToast("❌ Network error updating category privacy");
    }
}

async function addPrivacyIgnored() {
    const id = document.getElementById('privacyChannelSelect').value;
    if (!id || ignoredChannels.includes(id)) return;
    ignoredChannels.push(id);
    document.getElementById('privacyChannelSelect').value = '';
    await updatePrivacy();
    showToast("🔒 Channel exempted from lockdown");
}

async function removePrivacyIgnored(nameDisplay) {
    const c = currentGuildChannels.find(ch => `#${ch.name}` === nameDisplay);
    const idToRemove = c ? c.id : nameDisplay;
    ignoredChannels = ignoredChannels.filter(id => id != idToRemove);
    await updatePrivacy();
}

async function updatePrivacy() {
    await fetch(`/api/guild/${currentGuildId}/privacy/ignored`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ ignored: ignoredChannels })
    });
    loadPrivacySettings();
}

// ───────────────────── Universal Emoji Rendering ─────────────────────
function renderEmojiHtmlOrChar(val, size = 22) {
    if (!val) return '❓';
    val = String(val).trim();

    // 1. Unescape HTML entities if previously escaped
    val = val.replace(/&lt;/g, '<').replace(/&gt;/g, '>').replace(/&amp;/g, '&');

    // 2. Custom animated Discord emoji: <a:name:id> or a:name:id
    const animMatch = val.match(/<?a:([a-zA-Z0-9_]+):([0-9]{15,22})>?/);
    if (animMatch) {
        const name = animMatch[1];
        const id = animMatch[2];
        return `<img class="discord-custom-emoji animated" src="https://cdn.discordapp.com/emojis/${id}.gif?size=48&quality=lossless" alt="${name}" title="${name}" style="width:${size}px; height:${size}px; vertical-align:middle; object-fit:contain; border-radius:3px;">`;
    }

    // 3. Custom static Discord emoji: <:name:id> or :name:id or name:id
    const staticMatch = val.match(/<?:?([a-zA-Z0-9_]+):([0-9]{15,22})>?/);
    if (staticMatch) {
        const name = staticMatch[1];
        const id = staticMatch[2];
        return `<img class="discord-custom-emoji" src="https://cdn.discordapp.com/emojis/${id}.png?size=48" alt="${name}" title="${name}" style="width:${size}px; height:${size}px; vertical-align:middle; object-fit:contain; border-radius:3px;">`;
    }

    // 4. Pure Snowflake ID (15-22 digits)
    if (/^[0-9]{15,22}$/.test(val)) {
        let isAnimated = false;
        let emName = 'custom_emoji';
        if (typeof currentServerEmojis !== 'undefined' && Array.isArray(currentServerEmojis)) {
            const found = currentServerEmojis.find(e => String(e.id) === val);
            if (found) {
                isAnimated = !!found.animated;
                emName = found.name;
            }
        }
        const ext = isAnimated ? 'gif?size=48&quality=lossless' : 'png?size=48';
        return `<img class="discord-custom-emoji${isAnimated ? ' animated' : ''}" src="https://cdn.discordapp.com/emojis/${val}.${ext}" alt="${emName}" title="${emName}" style="width:${size}px; height:${size}px; vertical-align:middle; object-fit:contain; border-radius:3px;">`;
    }

    // 5. Server emoji by colon name or plain name (:name: or name)
    const clean = val.replace(/^:+|:+$/g, '').toLowerCase();
    if (typeof currentServerEmojis !== 'undefined' && Array.isArray(currentServerEmojis)) {
        const found = currentServerEmojis.find(e => e.name && e.name.toLowerCase() === clean);
        if (found) {
            const ext = found.animated ? 'gif?size=48&quality=lossless' : 'png?size=48';
            const url = found.url || `https://cdn.discordapp.com/emojis/${found.id}.${ext}`;
            return `<img class="discord-custom-emoji${found.animated ? ' animated' : ''}" src="${url}" alt="${found.name}" title="${found.name}" style="width:${size}px; height:${size}px; vertical-align:middle; object-fit:contain; border-radius:3px;">`;
        }
    }

    // 6. Contains any custom emoji inside a string or markdown
    if (val.includes('<a:') || val.includes('<:') || val.includes('&lt;a:') || val.includes('&lt;:')) {
        return renderDiscordMarkdown(val);
    }

    return escapeHtml(val);
}
window.renderEmojiHtmlOrChar = renderEmojiHtmlOrChar;

function addRrMappingRow(initialEmoji = '🎉', initialRoleId = '') {
    const container = document.getElementById('rrMappingsContainer');
    if (!container) return;
    const rowId = ++rrMappingCounter;
    const mappingObj = { id: rowId, emoji: initialEmoji, roleId: initialRoleId };
    rrMappings.push(mappingObj);

    const row = document.createElement('div');
    row.className = 'rr-mapping-row';
    row.id = `rrMappingRow_${rowId}`;

    const rolesOptions = '<option value="">Select a role to assign...</option>' +
        currentGuildRoles.map(r => `<option value="${r.id}" ${r.id === initialRoleId ? 'selected' : ''}>${r.name}</option>`).join('');

    row.innerHTML = `
        <div class="rr-emoji-picker-container">
            <button type="button" class="rr-emoji-preview-btn" id="rrEmojiBtn_${rowId}" title="Click to pick server or standard emoji">
                ${renderEmojiHtmlOrChar(initialEmoji)}
            </button>
            <input type="text" class="text-input rr-emoji-input" id="rrEmojiInput_${rowId}" value="${escapeHtml(initialEmoji)}" placeholder="Emoji e.g. 🎮" title="Type or paste emoji">
        </div>
        <select class="text-input rr-role-select" id="rrRoleSelect_${rowId}">
            ${rolesOptions}
        </select>
        <button type="button" class="btn btn-danger rr-remove-btn" id="rrRemoveBtn_${rowId}" title="Remove pairing">
            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><line x1="18" y1="6" x2="6" y2="18"></line><line x1="6" y1="6" x2="18" y2="18"></line></svg>
        </button>
    `;

    const emojiBtn = row.querySelector(`#rrEmojiBtn_${rowId}`);
    const emojiInput = row.querySelector(`#rrEmojiInput_${rowId}`);
    const roleSelect = row.querySelector(`#rrRoleSelect_${rowId}`);
    const removeBtn = row.querySelector(`#rrRemoveBtn_${rowId}`);

    emojiBtn.addEventListener('click', (e) => {
        e.stopPropagation();
        openEmojiPicker(emojiBtn, (chosenEmoji) => {
            emojiInput.dataset.rawEmoji = chosenEmoji;
            const m = chosenEmoji.match(/<a?:([a-zA-Z0-9_]+):[0-9]+>/);
            emojiInput.value = m ? `:${m[1]}:` : chosenEmoji;
            mappingObj.emoji = chosenEmoji;
            emojiBtn.innerHTML = renderEmojiHtmlOrChar(chosenEmoji);
            updateRrEmbedPreview();
        });
    });

    emojiInput.addEventListener('input', (e) => {
        const val = e.target.value.trim();
        mappingObj.emoji = val;
        emojiBtn.innerHTML = renderEmojiHtmlOrChar(val);
        updateRrEmbedPreview();
    });

    roleSelect.addEventListener('change', (e) => {
        mappingObj.roleId = e.target.value;
        updateRrEmbedPreview();
    });

    removeBtn.addEventListener('click', () => {
        row.remove();
        rrMappings = rrMappings.filter(m => m.id !== rowId);
        updateRrEmbedPreview();
    });

    container.appendChild(row);
    updateRrEmbedPreview();
}

function refreshAllRrRoleSelects() {
    rrMappings.forEach(m => {
        const sel = document.getElementById(`rrRoleSelect_${m.id}`);
        if (sel) {
            const currentVal = sel.value || m.roleId;
            sel.innerHTML = '<option value="">Select a role to assign...</option>' +
                currentGuildRoles.map(r => `<option value="${r.id}" ${r.id === currentVal ? 'selected' : ''}>${r.name}</option>`).join('');
            m.roleId = sel.value;
        }
    });
}

function updateRrEmbedPreview() {
    const titleEl = document.getElementById('rrTitleInput');
    const descEl = document.getElementById('rrDescInput');
    const simTitle = document.getElementById('rrSimTitle');
    const simDesc = document.getElementById('rrSimDesc');
    const simRolesList = document.getElementById('rrSimRolesList');
    const simReactionsRow = document.getElementById('rrSimReactionsRow');

    if (!simTitle || !simDesc || !simRolesList || !simReactionsRow) return;

    // Apply color theme to embed left border
    const simEmbed = document.getElementById('rrEmbedSimulation');
    if (simEmbed) {
        simEmbed.style.borderLeftColor = currentRrColor;
    }

    // Apply thumbnail
    const simThumb = document.getElementById('rrSimThumbnail');
    const simThumbImg = document.getElementById('rrSimThumbnailImg');
    if (simThumb && simThumbImg) {
        if (currentRrShowThumbnail && currentBotAvatar) {
            simThumb.style.display = 'block';
            simThumbImg.src = currentBotAvatar;
        } else {
            simThumb.style.display = 'none';
        }
    }

    // Apply custom footer
    const simFooterText = document.getElementById('rrSimFooterText');
    const simFooterIcon = document.getElementById('rrSimFooterIcon');
    if (simFooterText) {
        simFooterText.textContent = currentRrFooterText || 'React below to claim your roles!';
    }
    if (simFooterIcon) {
        if (currentBotAvatar) {
            simFooterIcon.style.display = 'block';
            simFooterIcon.src = currentBotAvatar;
        } else {
            simFooterIcon.style.display = 'none';
        }
    }

    simTitle.innerHTML = renderDiscordMarkdown((titleEl && titleEl.value.trim()) ? titleEl.value.trim() : '✨ Choose Your Roles');
    const rawDesc = descEl ? descEl.value : 'React below to claim your notification & community roles!';
    simDesc.innerHTML = renderDiscordMarkdown(rawDesc);

    let rolesHtml = '';
    let reactionsHtml = '';
    let validCount = 0;

    rrMappings.forEach(m => {
        const emojiVal = m.emoji ? m.emoji.trim() : '';
        const role = currentGuildRoles.find(r => r.id === m.roleId);
        const roleName = role ? role.name : 'Select a Role';
        const roleColor = role && role.color && role.color !== '#000000' && role.color !== '#94a3b8' ? role.color : '#c9cdfb';

        if (emojiVal || role) {
            validCount++;
            rolesHtml += `
                <div style="display: flex; align-items: center; gap: 8px; margin-bottom: 6px;">
                    <span style="font-size: 16px; min-width: 20px; display: inline-flex; align-items: center;">${renderEmojiHtmlOrChar(emojiVal)}</span>
                    <span style="color: #949ba4;">—</span>
                    <span class="discord-mention" style="color: ${roleColor}; font-weight: 600;">@${escapeHtml(roleName)}</span>
                </div>
            `;
        }

        if (emojiVal) {
            reactionsHtml += `
                <div class="discord-reaction-pill">
                    <span style="display: inline-flex; align-items: center;">${renderEmojiHtmlOrChar(emojiVal)}</span>
                    <span class="discord-reaction-count">1</span>
                </div>
            `;
        }
    });

    if (validCount === 0) {
        simRolesList.innerHTML = `<span style="color: #949ba4; font-size: 13px;">No role pairings added yet. Click "+ Add Pair" to configure.</span>`;
    } else {
        simRolesList.innerHTML = rolesHtml;
    }

    simReactionsRow.innerHTML = reactionsHtml;
    if (currentBotAvatar) {
        updateBotAvatars(currentBotAvatar);
    }
}

window.insertRrVar = function (text) {
    const richEl = document.getElementById('rrDescInput_rich');
    if (richEl) {
        insertEmojiOrTextIntoRichEditor(richEl, text);
        return;
    }
    const input = document.getElementById('rrDescInput');
    if (!input) return;
    const start = input.selectionStart || input.value.length;
    const end = input.selectionEnd || input.value.length;
    input.value = input.value.substring(0, start) + text + input.value.substring(end);
    input.focus();
    input.selectionStart = input.selectionEnd = start + text.length;
    updateRrEmbedPreview();
};

async function loadReactionRolesSettings() {
    try {
        const resp = await fetch(`/api/guild/${currentGuildId}/reaction_roles`);
        const data = await resp.json();
        if (data.mappings && Array.isArray(data.mappings) && data.mappings.length > 0) {
            rrMappings = [];
            const container = document.getElementById('rrMappingsContainer');
            if (container) container.innerHTML = '';
            data.mappings.forEach(m => {
                addRrMappingRow(m.emoji, String(m.role_id));
            });
        }
    } catch (e) {}
    syncAllRichEmojiEditors();
    updateRrEmbedPreview();
}

async function deployReactionPanel() {
    const channelSelect = document.getElementById('rrChannelSelect');
    const channelId = channelSelect.value;
    if (!channelId) {
        return showToast('⚠️ Select a channel to post the reaction panel in!');
    }

    const title = document.getElementById('rrTitleInput').value.trim() || 'Role Assignment';
    const description = document.getElementById('rrDescInput').value.trim() || 'React below to get your roles!';

    const validMappings = [];
    for (const m of rrMappings) {
        if (!m.roleId) continue;
        if (!m.emoji || !m.emoji.trim()) continue;
        validMappings.push({
            role_id: m.roleId,
            emoji: m.emoji.trim()
        });
    }

    if (validMappings.length === 0) {
        return showToast('⚠️ Add at least one valid role & emoji pairing before deploying!');
    }

    const deployBtn = document.getElementById('deployReactionPanelBtn');
    deployBtn.disabled = true;
    const origHtml = deployBtn.innerHTML;
    deployBtn.innerHTML = `<span>⏳</span> Deploying Panel to Discord...`;

    try {
        const resp = await fetch(`/api/guild/${currentGuildId}/reaction_roles/create`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                channel_id: channelId,
                title: title,
                description: description,
                mappings: validMappings,
                color: currentRrColor,
                show_thumbnail: currentRrShowThumbnail,
                footer: currentRrFooterText
            })
        });
        const data = await resp.json();
        if (data.success) {
            showToast(`🎉 Reaction Panel deployed in #${data.channel_name}! (${data.count} roles mapped)`);
        } else {
            showToast(`❌ Error: ${data.error || 'Failed to deploy panel'}`);
        }
    } catch (err) {
        showToast("❌ Network error deploying reaction panel");
    } finally {
        deployBtn.disabled = false;
        deployBtn.innerHTML = origHtml;
    }
}

// ───────────────────── Whitelist & Tags Rendering ─────────────────────
async function addWhitelistUser(type) {
    const select = type === 'antinuke' ? document.getElementById('whitelistSelect') : document.getElementById('abuseWhitelistSelect');
    const userId = select.value;
    if (!userId) return showToast('⚠️ Select a member first');
    const ep = type === 'antinuke' ? `/api/guild/${currentGuildId}/whitelist/add` : `/api/guild/${currentGuildId}/antiabuse/whitelist/add`;
    const resp = await fetch(ep, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ user_id: userId })
    });
    const data = await resp.json();
    if (data.success) {
        select.value = '';
        showToast('🛡️ User granted immunity');
        if (type === 'antinuke') loadAntinukeSettings();
        else loadAntiabuseSettings();
    }
}

async function removeWhitelistUser(userId, type) {
    const ep = type === 'antinuke' ? `/api/guild/${currentGuildId}/whitelist/remove` : `/api/guild/${currentGuildId}/antiabuse/whitelist/remove`;
    await fetch(ep, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ user_id: userId })
    });
    showToast('User removed from whitelist');
    if (type === 'antinuke') loadAntinukeSettings();
    else loadAntiabuseSettings();
}

function renderWhitelist(containerId, users, type) {
    const cont = document.getElementById(containerId);
    if (!cont) return;
    if (!users || users.length === 0) {
        cont.innerHTML = '<div class="whitelist-empty">No whitelisted members yet. Add trusted users above.</div>';
        return;
    }
    cont.innerHTML = '';
    users.forEach(u => {
        const item = document.createElement('div');
        item.className = 'whitelist-item';
        const avatarHtml = u.avatar ? `<img src="${u.avatar}" alt="">` : `<div class="default-avatar">${u.username.charAt(0).toUpperCase()}</div>`;
        item.innerHTML = `
            <div class="user-info">
                ${avatarHtml}
                <div>
                    <span class="user-name-text">${escapeHtml(u.username)}</span>
                    <span class="user-id-pill">${u.id}</span>
                </div>
            </div>
            <button class="btn btn-danger" style="padding: 5px 10px; font-size: 12px;">Remove</button>
        `;
        item.querySelector('button').addEventListener('click', () => removeWhitelistUser(u.id, type));
        cont.appendChild(item);
    });
}

function renderTags(containerId, items, onRemove) {
    const cont = document.getElementById(containerId);
    if (!cont) return;
    cont.innerHTML = '';
    if (items.length === 0) {
        cont.innerHTML = '<span style="font-size:13px; color:var(--text-muted); padding: 6px 0;">None configured yet.</span>';
        return;
    }
    items.forEach(i => {
        const tag = document.createElement('div');
        tag.className = 'tag';
        tag.innerHTML = `<span>${escapeHtml(String(i))}</span><span class="tag-remove">&times;</span>`;
        tag.querySelector('.tag-remove').addEventListener('click', () => onRemove(i));
        cont.appendChild(tag);
    });
}

// ───────────────────── Toast Utility ─────────────────────
function showToast(msg) {
    toastMessage.textContent = msg;
    toast.classList.add('show');
    setTimeout(() => toast.classList.remove('show'), 3000);
}

// ───────────────────── Announcements Logic ─────────────────────
async function loadAnnouncementsSettings() {
    try {
        const resp = await fetch(`/api/guild/${currentGuildId}/announcements`);
        const data = await resp.json();
        configuredAnnChannelId = data.channel_id;

        const badge = document.getElementById('annActiveChannelBadge');
        const destSelect = document.getElementById('annDestChannelSelect');

        if (configuredAnnChannelId) {
            if (destSelect) destSelect.value = configuredAnnChannelId;
            const composeSelect = document.getElementById('annComposeChannelSelect');
            if (composeSelect && !composeSelect.value) {
                composeSelect.value = configuredAnnChannelId;
            }
            const chanObj = currentGuildChannels.find(c => String(c.id) === String(configuredAnnChannelId));
            const chanName = chanObj ? `#${chanObj.name}` : `ID: ${configuredAnnChannelId}`;
            if (badge) {
                badge.textContent = `📢 Active: ${chanName}`;
                badge.style.background = 'rgba(45, 212, 191, 0.15)';
                badge.style.color = '#2dd4bf';
                badge.style.borderColor = 'rgba(45, 212, 191, 0.3)';
            }
        } else {
            if (destSelect) destSelect.value = '';
            if (badge) {
                badge.textContent = '⚠️ Not Configured (Silent)';
                badge.style.background = 'rgba(239, 68, 68, 0.15)';
                badge.style.color = '#f87171';
                badge.style.borderColor = 'rgba(239, 68, 68, 0.3)';
            }
        }

        syncAllRichEmojiEditors();
        updateAnnPreview();
    } catch (e) {
        console.error("Error loading announcements settings:", e);
    }
}

async function saveAnnouncementChannel() {
    const destSelect = document.getElementById('annDestChannelSelect');
    if (!destSelect) return;
    const channelId = destSelect.value;

    const btn = document.getElementById('saveAnnChannelBtn');
    const origHtml = btn.innerHTML;
    btn.disabled = true;
    btn.innerHTML = `<span>⏳</span> Saving...`;

    try {
        const resp = await fetch(`/api/guild/${currentGuildId}/announcements/channel`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ channel_id: channelId })
        });
        const data = await resp.json();
        if (data.success) {
            configuredAnnChannelId = data.channel_id;
            const chanObj = currentGuildChannels.find(c => String(c.id) === String(configuredAnnChannelId));
            const chanName = chanObj ? `#${chanObj.name}` : channelId;
            showToast(channelId ? `📢 Official Announcement Channel set to ${chanName}!` : `📢 Announcement Channel cleared.`);
            await loadAnnouncementsSettings();
        } else {
            showToast(`❌ Error: ${data.error || 'Failed to update channel'}`);
        }
    } catch (err) {
        showToast("❌ Network error saving announcement channel");
    } finally {
        btn.disabled = false;
        btn.innerHTML = origHtml;
    }
}

window.insertAnnVar = function (text) {
    const richEl = document.getElementById('annContentInput_rich');
    if (richEl) {
        insertEmojiOrTextIntoRichEditor(richEl, text);
        return;
    }
    const input = document.getElementById('annContentInput');
    if (!input) return;
    const start = input.selectionStart || input.value.length;
    const end = input.selectionEnd || input.value.length;
    input.value = input.value.substring(0, start) + text + input.value.substring(end);
    input.focus();
    input.selectionStart = input.selectionEnd = start + text.length;
    updateAnnPreview();
};

function updateAnnPreview() {
    const titleEl = document.getElementById('annTitleInput');
    const contentEl = document.getElementById('annContentInput');
    const simTitle = document.getElementById('annSimTitle');
    const simContent = document.getElementById('annSimContent');
    const simMentionRow = document.getElementById('annSimMentionRow');
    const simMentionPill = document.getElementById('annSimMentionPill');
    const simEmbed = document.getElementById('annEmbedSimulation');
    const simThumb = document.getElementById('annSimThumbnail');
    const simThumbImg = document.getElementById('annSimThumbnailImg');
    const simFooterText = document.getElementById('annSimFooterText');
    const simFooterIcon = document.getElementById('annSimFooterIcon');

    if (!simTitle || !simContent || !simEmbed) return;

    // Apply color theme to embed left border
    simEmbed.style.borderLeftColor = currentAnnColor;

    // Mention ping row
    if (simMentionRow && simMentionPill) {
        if (currentAnnPing === 'everyone') {
            simMentionRow.style.display = 'block';
            simMentionPill.textContent = '@everyone';
            simMentionPill.style.color = '#f87171';
            simMentionPill.style.background = 'rgba(239, 68, 68, 0.2)';
        } else if (currentAnnPing === 'here') {
            simMentionRow.style.display = 'block';
            simMentionPill.textContent = '@here';
            simMentionPill.style.color = '#fbbf24';
            simMentionPill.style.background = 'rgba(245, 158, 11, 0.2)';
        } else {
            simMentionRow.style.display = 'none';
        }
    }

    // Title
    const rawTitle = titleEl ? titleEl.value.trim() : '';
    simTitle.innerHTML = rawTitle ? renderDiscordMarkdown(rawTitle) : '📢 Official Announcement';

    // Content body with line-by-line markdown
    const rawContent = contentEl ? contentEl.value : '';
    simContent.innerHTML = renderDiscordMarkdown(rawContent);

    // Thumbnail
    if (simThumb && simThumbImg) {
        if (currentAnnShowThumbnail && currentBotAvatar) {
            simThumb.style.display = 'block';
            simThumbImg.src = currentBotAvatar;
        } else {
            simThumb.style.display = 'none';
        }
    }

    // Footer
    if (simFooterText) {
        simFooterText.textContent = currentAnnFooterText || 'Friday Broadcast System • Official Notification';
    }
    if (simFooterIcon) {
        if (currentBotAvatar && currentAnnShowThumbnail) {
            simFooterIcon.style.display = 'block';
            simFooterIcon.src = currentBotAvatar;
        } else {
            simFooterIcon.style.display = 'none';
        }
    }

    if (currentBotAvatar) {
        updateBotAvatars(currentBotAvatar);
    }
}

async function broadcastAnnouncement() {
    const composeSelect = document.getElementById('annComposeChannelSelect');
    let targetChannelId = composeSelect ? composeSelect.value : '';
    if (!targetChannelId) {
        targetChannelId = configuredAnnChannelId;
    }

    if (!targetChannelId) {
        return showToast('⚠️ Please select or configure a destination channel before broadcasting!');
    }

    const title = document.getElementById('annTitleInput') ? document.getElementById('annTitleInput').value.trim() : '';
    const content = document.getElementById('annContentInput') ? document.getElementById('annContentInput').value.trim() : '';

    if (!title && !content) {
        return showToast('⚠️ Enter a title or announcement message body!');
    }

    const btn = document.getElementById('broadcastAnnouncementBtn');
    btn.disabled = true;
    const origHtml = btn.innerHTML;
    btn.innerHTML = `<span>⏳</span> Broadcasting...`;

    try {
        const resp = await fetch(`/api/guild/${currentGuildId}/announcements/send`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                channel_id: targetChannelId,
                title: title,
                content: content,
                ping: currentAnnPing,
                color: currentAnnColor,
                show_thumbnail: currentAnnShowThumbnail,
                footer: currentAnnFooterText
            })
        });
        const data = await resp.json();
        if (data.success) {
            showToast(`🎉 Announcement broadcasted to #${data.channel_name}!`);
        } else {
            showToast(`❌ Error: ${data.error || 'Failed to broadcast announcement'}`);
        }
    } catch (err) {
        showToast("❌ Network error broadcasting announcement");
    } finally {
        btn.disabled = false;
        btn.innerHTML = origHtml;
    }
}

// ───────────────────── Ticket System Studio Logic ─────────────────────
let currentTicketColor = '#2dd4bf';

window.insertTicketVar = function (text) {
    const richEl = document.getElementById('ticketDescInput_rich');
    if (richEl) {
        insertEmojiOrTextIntoRichEditor(richEl, text);
        return;
    }
    const input = document.getElementById('ticketDescInput');
    if (!input) return;
    const start = input.selectionStart || 0;
    const end = input.selectionEnd || 0;
    const val = input.value;
    input.value = val.substring(0, start) + text + val.substring(end);
    input.focus();
    input.selectionStart = input.selectionEnd = start + text.length;
    updateTicketPreview();
};

function updateTicketButtonEmojiVisual(num) {
    const input = document.getElementById(`ticketBtn${num}`);
    const btn = document.getElementById(`ticketBtn${num}EmojiBtn`);
    if (!input || !btn) return;
    const raw = input.value.trim();
    const parsed = parseBtnForPreview(raw);
    if (parsed.emojiHtml) {
        btn.innerHTML = parsed.emojiHtml;
    } else {
        btn.textContent = '🙂';
    }
}

window.setTicketButtonEmoji = function (num, emojiStr) {
    const input = document.getElementById(`ticketBtn${num}`);
    if (!input) return;
    let val = input.value.trim();

    // Clean existing leading custom emoji <a?:name:id>, colon emoji :name:, or unicode emoji
    val = val.replace(/^<a?:[a-zA-Z0-9_]+:[0-9]+>\s*/, '');
    val = val.replace(/^:[a-zA-Z0-9_]+:\s*/, '');
    val = val.replace(/^[^\w\s\d<:]{1,4}\s*/, '');

    // Clean trailing or leftover colon emojis or duplicate unicode emojis
    val = val.replace(/\s*:[a-zA-Z0-9_]+:\s*$/, '').trim();
    val = val.replace(/:([a-zA-Z0-9_]+):/g, '').trim();
    val = val.replace(/\s*[^\w\s\d<:]{1,4}$/, '').trim();

    if (!val) {
        val = num === 1 ? 'General Support' : (num === 2 ? 'Giveaway Claim' : (num === 3 ? 'Report User' : 'Partnerships'));
    }

    // Put selected emoji at the 1st place!
    input.value = `${emojiStr} ${val}`;
    input.focus();
    if (input._syncToRich) input._syncToRich();
    updateTicketButtonEmojiVisual(num);
    updateTicketPreview();
};

function parseBtnForPreview(btnText) {
    let raw = (btnText || '').trim();
    let emojiHtml = '';
    let cleanLabel = raw;

    // 1. Custom emoji: <a:name:id> or <:name:id>
    const customMatch = raw.match(/<(a?):([a-zA-Z0-9_]+):([0-9]+)>/);
    if (customMatch) {
        const isAnim = customMatch[1] === 'a';
        const name = customMatch[2];
        const id = customMatch[3];
        const url = `https://cdn.discordapp.com/emojis/${id}.${isAnim ? 'gif' : 'png'}?size=48&quality=lossless`;
        emojiHtml = `<img class="discord-custom-emoji${isAnim ? ' animated' : ''}" src="${url}" alt="${name}" style="width: 18px; height: 18px; vertical-align: middle; margin-right: 6px; object-fit: contain;">`;
        cleanLabel = raw.replace(customMatch[0], '').trim();
    } else {
        // 2. Colon custom emoji: :name:
        const colonMatch = raw.match(/:([a-zA-Z0-9_]+):/);
        if (colonMatch) {
            const name = colonMatch[1].toLowerCase();
            const found = typeof currentServerEmojis !== 'undefined' ? currentServerEmojis.find(e => e.name.toLowerCase() === name) : null;
            if (found) {
                emojiHtml = `<img class="discord-custom-emoji${found.animated ? ' animated' : ''}" src="${found.url}" alt="${found.name}" style="width: 18px; height: 18px; vertical-align: middle; margin-right: 6px; object-fit: contain;">`;
            }
            cleanLabel = raw.replace(colonMatch[0], '').trim();
        } else {
            // 3. Leading unicode emoji
            const uniMatch = raw.match(/^([^\w\s\d<:]{1,4})\s*/);
            if (uniMatch) {
                emojiHtml = `<span style="font-size: 16px; margin-right: 6px; vertical-align: middle;">${uniMatch[1].trim()}</span>`;
                cleanLabel = raw.substring(uniMatch[0].length).trim();
            }
        }
    }

    // Clean any trailing or leftover colon emojis or duplicate standard emojis from label
    cleanLabel = cleanLabel.replace(/^([^\w\s\d<:]{1,4})\s*/, '').replace(/\s*([^\w\s\d<:]{1,4})$/, '').replace(/:([a-zA-Z0-9_]+):/g, '').trim();
    if (!cleanLabel) cleanLabel = "Support";

    return { emojiHtml, cleanLabel };
}

window.applyTicketPreset = function (type) {
    const b1 = document.getElementById('ticketBtn1');
    const b2 = document.getElementById('ticketBtn2');
    const b3 = document.getElementById('ticketBtn3');
    const b4 = document.getElementById('ticketBtn4');
    if (!b1) return;

    if (type === 'support') {
        b1.value = '💬 General Support';
        if (b2) b2.value = '';
        if (b3) b3.value = '';
        if (b4) b4.value = '';
    } else if (type === 'support_gw') {
        b1.value = '💬 General Support';
        if (b2) b2.value = '🎁 Giveaway Claim';
        if (b3) b3.value = '';
        if (b4) b4.value = '';
    } else if (type === 'full') {
        b1.value = '💬 General Support';
        if (b2) b2.value = '🎁 Giveaway Claim';
        if (b3) b3.value = '🛡️ Report User';
        if (b4) b4.value = '💼 Partnerships';
    }
    syncAllRichEmojiEditors();
    updateTicketPreview();
    showToast('✨ Ticket button preset applied!');
};

function updateTicketPreview() {
    const titleEl = document.getElementById('ticketTitleInput');
    const descEl = document.getElementById('ticketDescInput');
    const simTitle = document.getElementById('ticketSimTitle');
    const simDesc = document.getElementById('ticketSimDesc');
    const simEmbed = document.getElementById('ticketEmbedSimulation');
    const simThumb = document.getElementById('ticketSimThumbnail');
    const simThumbImg = document.getElementById('ticketSimThumbnailImg');
    const buttonsRow = document.getElementById('ticketSimButtonsRow');
    const simAvatar = document.getElementById('ticketSimAvatar');

    if (!simTitle || !simDesc || !simEmbed) return;

    // Apply color accent stripe
    simEmbed.style.borderLeftColor = currentTicketColor;

    // Update Avatar
    if (simAvatar && currentBotAvatar) {
        simAvatar.innerHTML = `<img src="${currentBotAvatar}" alt="Friday">`;
    }

    // Render Title
    const rawTitle = titleEl ? titleEl.value.trim() : '';
    simTitle.innerHTML = rawTitle ? renderDiscordMarkdown(rawTitle) : '🎫 Server Support & Help Desk';

    // Render Description with rich markdown & emojis
    const rawDesc = descEl ? descEl.value : '';
    simDesc.innerHTML = rawDesc ? renderDiscordMarkdown(rawDesc) : 'Click an inquiry button below to open a ticket.';

    // Thumbnail
    if (simThumb && simThumbImg) {
        if (currentBotAvatar) {
            simThumb.style.display = 'block';
            simThumbImg.src = currentBotAvatar;
        } else {
            simThumb.style.display = 'none';
        }
    }

    // Buttons Action Row - Render exactly as Discord secondary buttons with emoji at the 1st place!
    if (buttonsRow) {
        buttonsRow.innerHTML = '';
        const b1 = document.getElementById('ticketBtn1') ? document.getElementById('ticketBtn1').value.trim() : '';
        const b2 = document.getElementById('ticketBtn2') ? document.getElementById('ticketBtn2').value.trim() : '';
        const b3 = document.getElementById('ticketBtn3') ? document.getElementById('ticketBtn3').value.trim() : '';
        const b4 = document.getElementById('ticketBtn4') ? document.getElementById('ticketBtn4').value.trim() : '';

        const activeButtons = [b1, b2, b3, b4].filter(Boolean);
        if (activeButtons.length === 0) {
            activeButtons.push('💬 General Support');
        }

        activeButtons.forEach(btnText => {
            const { emojiHtml, cleanLabel } = parseBtnForPreview(btnText);
            const btnEl = document.createElement('button');
            btnEl.type = 'button';
            btnEl.className = 'discord-btn-secondary';
            btnEl.style.cssText = 'background: #4e5058; color: #ffffff; border: none; border-radius: 8px; padding: 7px 14px; font-size: 13px; font-weight: 500; display: inline-flex; align-items: center; justify-content: center; cursor: pointer; transition: background 0.15s ease; box-shadow: 0 1px 2px rgba(0,0,0,0.2);';
            btnEl.innerHTML = `${emojiHtml}<span>${escapeHtml(cleanLabel)}</span>`;
            btnEl.addEventListener('click', () => {
                showToast(`ℹ️ Simulated: Clicking "${cleanLabel}" opens an isolated ticket channel!`);
            });
            buttonsRow.appendChild(btnEl);
        });
    }

    [1, 2, 3, 4].forEach(n => updateTicketButtonEmojiVisual(n));
}

async function loadTicketsSettings() {
    try {
        const resp = await fetch(`/api/guild/${currentGuildId}/tickets`);
        const data = await resp.json();
        const roleSelect = document.getElementById('ticketRoleSelect');
        if (roleSelect && data.support_role_id) {
            roleSelect.value = String(data.support_role_id);
        }

        // Restore latest deployed panel OR saved config draft
        const panels = data.panels ? Object.values(data.panels) : [];
        const p = data.config || (panels.length > 0 ? panels[panels.length - 1] : null);
        if (p) {
            const chanSelect = document.getElementById('ticketPanelChannelSelect');
            if (chanSelect && p.channel_id) {
                chanSelect.value = String(p.channel_id);
            }

            const catSelect = document.getElementById('ticketCategorySelect');
            if (catSelect && p.category_id) {
                catSelect.value = String(p.category_id);
            }

            const transChanSelect = document.getElementById('ticketTranscriptChannelSelect');
            if (transChanSelect && p.transcript_channel_id !== undefined) {
                transChanSelect.value = p.transcript_channel_id ? String(p.transcript_channel_id) : '';
            }

            const transCatSelect = document.getElementById('ticketTranscriptCategorySelect');
            if (transCatSelect && p.transcript_category_id !== undefined) {
                transCatSelect.value = p.transcript_category_id ? String(p.transcript_category_id) : '';
            }

            const privToggle = document.getElementById('ticketPrivateToggle');
            if (privToggle && p.private !== undefined) {
                privToggle.checked = Boolean(p.private);
            }

            const transToggle = document.getElementById('ticketTranscriptToggle');
            if (transToggle && p.transcription !== undefined) {
                transToggle.checked = Boolean(p.transcription);
            }

            const titleInput = document.getElementById('ticketTitleInput');
            if (titleInput && p.title) {
                titleInput.value = p.title;
            }

            const descInput = document.getElementById('ticketDescInput');
            if (descInput && p.description) {
                descInput.value = p.description;
            }

            if (p.buttons && Array.isArray(p.buttons)) {
                const b1 = document.getElementById('ticketBtn1');
                const b2 = document.getElementById('ticketBtn2');
                const b3 = document.getElementById('ticketBtn3');
                const b4 = document.getElementById('ticketBtn4');
                if (b1) b1.value = p.buttons[0] || '';
                if (b2) b2.value = p.buttons[1] || '';
                if (b3) b3.value = p.buttons[2] || '';
                if (b4) b4.value = p.buttons[3] || '';
            }

            if (p.color) {
                let hex;
                if (typeof p.color === 'number') {
                    hex = '#' + p.color.toString(16).padStart(6, '0');
                } else {
                    hex = String(p.color);
                }
                currentTicketColor = hex;
                const hexEl = document.getElementById('ticketColorHexCode');
                if (hexEl) hexEl.textContent = hex;
                const colInput = document.getElementById('ticketCustomColorInput');
                if (colInput) colInput.value = hex;
                document.querySelectorAll('.ticket-theme-chip').forEach(c => {
                    c.classList.toggle('active', c.dataset.color.toLowerCase() === hex.toLowerCase());
                });
            }
        }
    } catch (e) {
        console.error("Failed to load ticket settings", e);
    } finally {
        syncAllRichEmojiEditors();
        updateTicketPreview();
    }
}

async function saveTicketConfig() {
    const btn = document.getElementById('saveTicketConfigBtn');
    const channel_id = document.getElementById('ticketPanelChannelSelect').value;
    const category_id = document.getElementById('ticketCategorySelect').value;
    const support_role_id = document.getElementById('ticketRoleSelect').value;
    const transcript_channel_id = document.getElementById('ticketTranscriptChannelSelect').value;
    const transcript_category_id = document.getElementById('ticketTranscriptCategorySelect').value;
    
    const title = document.getElementById('ticketTitleInput').value;
    const desc = document.getElementById('ticketDescInput').value;
    
    const b1 = document.getElementById('ticketBtn1').value;
    const b2 = document.getElementById('ticketBtn2').value;
    const b3 = document.getElementById('ticketBtn3').value;
    const b4 = document.getElementById('ticketBtn4').value;
    
    const privateTicket = document.getElementById('ticketPrivateToggle').checked;
    const transcription = document.getElementById('ticketTranscriptToggle').checked;

    if (btn) btn.disabled = true;

    try {
        const payload = {
channel_id,
            category_id,
            support_role_id,
            transcript_channel_id,
            transcript_category_id,
            title,
            description: desc,
            buttons: [b1, b2, b3, b4].filter(x => x.trim() !== ''),
            private: privateTicket,
            transcription,
            color: currentTicketColor
        };

        const resp = await fetch(`/api/guild/${currentGuildId}/tickets/config`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(payload)
        });
        const data = await resp.json();
        if (data.success) {
            showToast('💾 Ticket settings draft saved successfully!');
        } else {
            showToast('❌ ' + (data.error || 'Failed to save settings'));
        }
    } catch(e) {
        showToast('❌ Network error saving ticket settings');
    } finally {
        if (btn) btn.disabled = false;
    }
}

async function deployTicketPanel() {
    const btn = document.getElementById('deployTicketPanelBtn');
    
    const channel_id = document.getElementById('ticketPanelChannelSelect').value;
    const category_id = document.getElementById('ticketCategorySelect').value;
    const support_role_id = document.getElementById('ticketRoleSelect').value;
    const transcript_channel_id = document.getElementById('ticketTranscriptChannelSelect').value;
    const transcript_category_id = document.getElementById('ticketTranscriptCategorySelect').value;
    
    const title = document.getElementById('ticketTitleInput').value;
    const desc = document.getElementById('ticketDescInput').value;
    
    const b1 = document.getElementById('ticketBtn1').value;
    const b2 = document.getElementById('ticketBtn2').value;
    const b3 = document.getElementById('ticketBtn3').value;
    const b4 = document.getElementById('ticketBtn4').value;
    
    const privateTicket = document.getElementById('ticketPrivateToggle').checked;
    const transcription = document.getElementById('ticketTranscriptToggle').checked;

    if (!channel_id) return showToast('⚠️ Select a Panel Channel!');
    if (!category_id) return showToast('⚠️ Select a Ticket Category!');
    if (!b1.trim()) return showToast('⚠️ Button 1 is required!');

    btn.disabled = true;
    const origHtml = btn.innerHTML;
    btn.innerHTML = `<span>⏳</span> Deploying...`;

    try {
        // First save support role
        await fetch(`/api/guild/${currentGuildId}/tickets`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ support_role_id })
        });

        // Then deploy panel with theme color & transcript destination
        const payload = {
channel_id,
            category_id,
            title,
            description: desc,
            buttons: [b1, b2, b3, b4].filter(x => x.trim() !== ''),
            private: privateTicket,
            transcription,
            transcript_channel_id,
            transcript_category_id,
            color: currentTicketColor
        };

        const resp = await fetch(`/api/guild/${currentGuildId}/tickets/panel`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(payload)
        });
        
        const data = await resp.json();
        if (data.success) {
            showToast('🎉 Interactive Ticket Panel deployed to your server!');
        } else {
            showToast('❌ Error: ' + (data.error || 'Failed to deploy panel'));
        }
    } catch (e) {
        showToast('❌ Network Error deploying panel');
    } finally {
        btn.disabled = false;
        btn.innerHTML = origHtml;
    }
}

// ───────────────────── Mention Autocomplete System ─────────────────────
let activeMentionInput = null;
let mentionMatchStart = -1;

function setupMentionAutocomplete() {
    const popover = document.getElementById('mentionAutocompletePopover');
    const popoverList = document.getElementById('mentionPopoverList');
    if (!popover || !popoverList) return;

    const targetSelectors = [
        '#annContentInput', '#annTitleInput',
        '#ticketTitleInput', '#ticketDescInput',
        '#ticketBtn1', '#ticketBtn2', '#ticketBtn3', '#ticketBtn4',
        '#levelMessageInput', '#rrTitleInput', '#rrDescInput'
    ];

    document.querySelectorAll(targetSelectors.join(',')).forEach(el => {
        el.addEventListener('input', () => handleMentionInput(el));
        el.addEventListener('keydown', (e) => {
            if (popover.classList.contains('open') && e.key === 'Escape') {
                closeMentionPopover();
            }
        });
    });

    document.addEventListener('click', (e) => {
        if (!popover.contains(e.target) && e.target !== activeMentionInput) {
            closeMentionPopover();
        }
    });
}

function handleMentionInput(inputEl) {
    const popover = document.getElementById('mentionAutocompletePopover');
    const popoverList = document.getElementById('mentionPopoverList');
    if (!popover || !popoverList) return;

    const cursor = inputEl.selectionStart;
    const text = inputEl.value.slice(0, cursor);
    
    // Check if we just typed @ or @something without whitespace
    const match = text.match(/@([a-zA-Z0-9_]*)$/);
    if (!match) {
        closeMentionPopover();
        return;
    }

    activeMentionInput = inputEl;
    mentionMatchStart = cursor - match[0].length;
    const query = match[1].toLowerCase();

    // Collect matching roles and members
    const roles = (currentGuildRoles || []).filter(r => r.name.toLowerCase().includes(query));
    const members = (currentGuildMembers || []).filter(m => m.username.toLowerCase().includes(query));

    popoverList.innerHTML = '';

    // Special mentions
    if ('everyone'.includes(query)) {
        appendMentionItem(popoverList, {
            type: 'special',
            tag: '@everyone',
            label: '@everyone',
            sub: 'Notify all members in channel',
            color: '#f87171'
        });
    }
    if ('here'.includes(query)) {
        appendMentionItem(popoverList, {
            type: 'special',
            tag: '@here',
            label: '@here',
            sub: 'Notify online members in channel',
            color: '#fbbf24'
        });
    }

    // Roles (up to 8)
    roles.slice(0, 8).forEach(r => {
        appendMentionItem(popoverList, {
            type: 'role',
            tag: `<@&${r.id}>`,
            label: `@${r.name}`,
            sub: `Role • ${r.id}`,
            color: r.color || '#5865f2'
        });
    });

    // Members (up to 10)
    members.slice(0, 10).forEach(m => {
        appendMentionItem(popoverList, {
            type: 'member',
            tag: `<@${m.id}>`,
            label: `@${m.username}`,
            sub: `Member • ${m.id}`,
            avatar: m.avatar
        });
    });

    if (popoverList.children.length === 0) {
        popoverList.innerHTML = '<div style="padding: 10px; font-size: 12px; color: #949ba4; text-align: center;">No matching roles or members</div>';
    }

    // Position popover relative to input element
    const rect = inputEl.getBoundingClientRect();
    popover.style.position = 'fixed';
    popover.style.left = `${Math.max(10, Math.min(window.innerWidth - 300, rect.left))}px`;
    
    let top = rect.bottom + 6;
    if (top + 260 > window.innerHeight) {
        top = Math.max(10, rect.top - 260);
    }
    popover.style.top = `${top}px`;
    popover.classList.add('open');
}

function appendMentionItem(container, item) {
    const div = document.createElement('div');
    div.className = 'mention-popover-item';
    
    let iconHtml = '';
    if (item.avatar) {
        iconHtml = `<img src="${item.avatar}" style="width: 20px; height: 20px; border-radius: 50%; object-fit: cover;" alt="">`;
    } else {
        const bg = item.color || '#5865f2';
        iconHtml = `<div style="width: 14px; height: 14px; border-radius: 50%; background: ${bg}; flex-shrink: 0;"></div>`;
    }

    div.innerHTML = `
        <div style="display: flex; align-items: center; gap: 8px; flex: 1; min-width: 0;">
            ${iconHtml}
            <span class="mention-item-name" style="color: ${item.color || '#ffffff'};">${escapeHtml(item.label)}</span>
        </div>
        <span class="mention-item-sub">${escapeHtml(item.sub)}</span>
    `;

    div.addEventListener('click', (e) => {
        e.preventDefault();
        e.stopPropagation();
        insertMentionTag(item.tag);
    });

    container.appendChild(div);
}

function insertMentionTag(tag) {
    if (!activeMentionInput || mentionMatchStart < 0) return;
    const input = activeMentionInput;
    const val = input.value;
    const cursor = input.selectionStart;
    
    // Replace text from mentionMatchStart to cursor with tag + ' '
    const before = val.slice(0, mentionMatchStart);
    const after = val.slice(cursor);
    input.value = before + tag + ' ' + after;
    
    const newPos = before.length + tag.length + 1;
    input.selectionStart = input.selectionEnd = newPos;
    input.focus();
    
    closeMentionPopover();
    
    // Trigger input event for live preview updates!
    input.dispatchEvent(new Event('input', { bubbles: true }));
}

function closeMentionPopover() {
    const popover = document.getElementById('mentionAutocompletePopover');
    if (popover) popover.classList.remove('open');
    activeMentionInput = null;
    mentionMatchStart = -1;
}


// ───────────────────── Member Real-time Search ─────────────────────
function setupMemberSearch() {
    function filterSelect(searchInputId, selectId) {
        const searchInput = document.getElementById(searchInputId);
        const select = document.getElementById(selectId);
        if (!searchInput || !select) return;
        
        searchInput.addEventListener('input', (e) => {
            const query = e.target.value.toLowerCase();
            Array.from(select.options).forEach(opt => {
                if (opt.value === "") return; // Skip placeholder
                const text = opt.text.toLowerCase();
                opt.style.display = text.includes(query) ? '' : 'none';
            });
        });
    }
    
    filterSelect('whitelistSearch', 'whitelistSelect');
    filterSelect('abuseWhitelistSearch', 'abuseWhitelistSelect');
}


// ───────────────────── Custom Searchable Select ─────────────────────
function initCustomSelects() {
    document.querySelectorAll('select.searchable-select').forEach(select => {
        if (select.nextElementSibling && select.nextElementSibling.classList.contains('custom-select-wrapper')) {
            select.nextElementSibling.remove();
        }
        
        select.style.display = 'none'; // hide original select
        
        const wrapper = document.createElement('div');
        wrapper.className = 'custom-select-wrapper';
        
        const trigger = document.createElement('div');
        trigger.className = 'custom-select-trigger';
        trigger.innerHTML = `<span>${select.options[select.selectedIndex]?.text || 'Select...'}</span>
            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                <path d="m6 9 6 6 6-6"/>
            </svg>`;
            
        const dropdown = document.createElement('div');
        dropdown.className = 'custom-select-dropdown';
        
        const searchBox = document.createElement('div');
        searchBox.className = 'custom-select-search';
        const searchInput = document.createElement('input');
        searchInput.type = 'text';
        searchInput.placeholder = 'Search...';
        searchBox.appendChild(searchInput);
        
        const optionsContainer = document.createElement('div');
        optionsContainer.className = 'custom-select-options';
        
        function renderOptions(query = '') {
            optionsContainer.innerHTML = '';
            Array.from(select.options).forEach(opt => {
                if (opt.value === "") return; // Skip empty placeholder
                if (opt.text.toLowerCase().includes(query.toLowerCase())) {
                    const optEl = document.createElement('div');
                    optEl.className = 'custom-select-option' + (opt.selected ? ' selected' : '');
                    optEl.textContent = opt.text;
                    optEl.addEventListener('click', () => {
                        select.value = opt.value;
                        select.dispatchEvent(new Event('change'));
                        trigger.querySelector('span').textContent = opt.text;
                        wrapper.classList.remove('open');
                        renderOptions(); // Reset selected state
                    });
                    optionsContainer.appendChild(optEl);
                }
            });
        }
        
        renderOptions();
        
        dropdown.appendChild(searchBox);
        dropdown.appendChild(optionsContainer);
        wrapper.appendChild(trigger);
        wrapper.appendChild(dropdown);
        select.parentNode.insertBefore(wrapper, select.nextSibling);
        
        trigger.addEventListener('click', (e) => {
            document.querySelectorAll('.custom-select-wrapper').forEach(w => {
                if (w !== wrapper) w.classList.remove('open');
            });
            wrapper.classList.toggle('open');
            if (wrapper.classList.contains('open')) {
                searchInput.focus();
                searchInput.value = '';
                renderOptions();
            }
        });
        
        searchInput.addEventListener('input', (e) => renderOptions(e.target.value));
        
        document.addEventListener('click', (e) => {
            if (!wrapper.contains(e.target)) wrapper.classList.remove('open');
        });
        
        // Sync trigger text if original select changes externally
        select.addEventListener('change', () => {
            const selectedOpt = select.options[select.selectedIndex];
            if (selectedOpt) trigger.querySelector('span').textContent = selectedOpt.text;
        });
    });
}


// ───────────────────── Custom Bot Responses (Comprehensive Codebase Audit) ─────────────────────
const ALL_RESPONSE_FIELDS = [
    'resp_ban_success',
    'resp_unban_success',
    'resp_timeout_success',
    'resp_untimeout_success',
    'resp_purge_success',
    'resp_nick_success',
    'resp_nick_reset',
    'resp_announcement_confirm_prompt',
    'resp_announcement_broadcast_success',
    'resp_announcement_cancel',
    'resp_announcement_timeout',
    'resp_announcement_access_denied',
    'resp_announcement_perm_err',
    'resp_ticket_welcome_msg',
    'resp_ticket_already_open',
    'resp_ticket_created_ack',
    'resp_ticket_closing_msg',
    'resp_ticket_created_success',
    'resp_abuse_warning_msg',
    'resp_abuse_edit_warning_msg',
    'resp_security_invite_warn',
    'resp_security_spam_warn',
    'resp_security_link_warn',
    'resp_perm_err_timeout',
    'resp_admin_timeout_err',
    'resp_not_timed_out',
    'resp_perm_err_ban',
    'resp_perm_err_unban',
    'resp_perm_err_purge',
    'resp_hierarchy_err',
    'resp_unban_not_found',
    'resp_nick_perm_err',
    'resp_nick_bot_err',
    'resp_level_up_msg',
    'resp_lockdown_initiated',
    'resp_lockdown_lifted'
];

async function loadResponsesSettings() {
    try {
        const resp = await fetch(`/api/guild/${currentGuildId}/responses`);
        const data = await resp.json();
        if (data.success && data.config) {
            ALL_RESPONSE_FIELDS.forEach(fieldId => {
                const key = fieldId.replace('resp_', '');
                const input = document.getElementById(fieldId);
                if (input && data.config[key] !== undefined) {
                    input.value = data.config[key];
                }
            });
            document.querySelectorAll('input[id^="resp_"]').forEach(input => {
                const key = input.id.replace('resp_', '');
                if (data.config[key] !== undefined) {
                    input.value = data.config[key];
                }
            });
            const autoAiInput = document.getElementById('autoAiThinkingInput');
            if (autoAiInput && data.config['ai_thinking'] !== undefined) {
                autoAiInput.value = data.config['ai_thinking'];
            }
        }
    } catch(e) {
        console.error("Failed to load custom responses", e);
    }
}



const CUSTOM_RESPONSES_SCHEMA = [
    {"id": "ban_success", "label": "Ban Success Message", "category": "Moderation", "vars": ["{member}", "{reason}"]},
    {"id": "unban_success", "label": "Unban Success Message", "category": "Moderation", "vars": ["{member}"]},
    {"id": "timeout_success", "label": "Timeout Success Message", "category": "Moderation", "vars": ["{member}", "{minutes}", "{reason}"]},
    {"id": "untimeout_success", "label": "Untimeout Success Message", "category": "Moderation", "vars": ["{member}"]},
    {"id": "purge_success", "label": "Purge Messages Success", "category": "Moderation", "vars": ["{count}"]},
    {"id": "warn_success", "label": "Warning Issued Message", "category": "Moderation", "vars": ["{member}", "{reason}", "{warns}"]},
    {"id": "nick_success", "label": "Nickname Change Success", "category": "Moderation", "vars": ["{member}", "{nick}"]},
    {"id": "nick_reset", "label": "Nickname Reset Success", "category": "Moderation", "vars": ["{member}"]},
    {"id": "announcement_confirm_prompt", "label": "Broadcast Confirmation Prompt", "category": "Announcements", "vars": ["{channel}"]},
    {"id": "announcement_broadcast_success", "label": "Broadcast Sent Successfully", "category": "Announcements", "vars": ["{channel}", "{url}"]},
    {"id": "announcement_cancel", "label": "Broadcast Cancelled Notice", "category": "Announcements", "vars": []},
    {"id": "announcement_timeout", "label": "Broadcast Timed Out Notice", "category": "Announcements", "vars": []},
    {"id": "announcement_access_denied", "label": "Announcement Permission Denied Alert", "category": "Announcements", "vars": []},
    {"id": "announcement_perm_err", "label": "Bot Missing Perms in Announcement Channel", "category": "Announcements", "vars": ["{channel}"]},
    {"id": "ticket_welcome_msg", "label": "Welcome Message Inside Ticket", "category": "Tickets", "vars": ["{member}"]},
    {"id": "ticket_already_open", "label": "Existing Ticket Open Alert", "category": "Tickets", "vars": ["{channel}"]},
    {"id": "ticket_created_ack", "label": "Ticket Creation Acknowledgement", "category": "Tickets", "vars": []},
    {"id": "ticket_closing_msg", "label": "Ticket Closing Countdown", "category": "Tickets", "vars": []},
    {"id": "ticket_created_success", "label": "Ticket Created Direct Confirmation", "category": "Tickets", "vars": ["{channel}"]},
    {"id": "abuse_warning_msg", "label": "Banned Word Warning", "category": "Security & Filters", "vars": ["{member}"]},
    {"id": "abuse_edit_warning_msg", "label": "Edited Message Banned Word Warning", "category": "Security & Filters", "vars": ["{member}"]},
    {"id": "security_invite_warn", "label": "Unauthorized Invite Link Warning", "category": "Security & Filters", "vars": ["{member}"]},
    {"id": "security_spam_warn", "label": "Rapid Spam Velocity Warning", "category": "Security & Filters", "vars": ["{member}"]},
    {"id": "security_link_warn", "label": "External Link Warning", "category": "Security & Filters", "vars": ["{member}"]},
    {"id": "perm_err_timeout", "label": "Timeout Permission / Role Error", "category": "Permissions & Ephemeral Errors", "vars": ["{member}"]},
    {"id": "admin_timeout_err", "label": "Administrator Timeout Restriction", "category": "Permissions & Ephemeral Errors", "vars": []},
    {"id": "not_timed_out", "label": "Target Not Timed Out Alert", "category": "Permissions & Ephemeral Errors", "vars": ["{member}"]},
    {"id": "perm_err_ban", "label": "Ban Permission / Role Error", "category": "Permissions & Ephemeral Errors", "vars": ["{member}"]},
    {"id": "perm_err_unban", "label": "Unban Permission Error", "category": "Permissions & Ephemeral Errors", "vars": []},
    {"id": "unban_not_found", "label": "Unban Target Not Found", "category": "Permissions & Ephemeral Errors", "vars": ["{user}"]},
    {"id": "perm_err_purge", "label": "Purge Permission Error", "category": "Permissions & Ephemeral Errors", "vars": []},
    {"id": "hierarchy_err", "label": "Staff Role Hierarchy Alert", "category": "Permissions & Ephemeral Errors", "vars": ["{member}"]},
    {"id": "nick_perm_err", "label": "Staff Missing Manage Nicknames Perm", "category": "Permissions & Ephemeral Errors", "vars": []},
    {"id": "nick_bot_err", "label": "Bot Role Lower Than Target (Nickname)", "category": "Permissions & Ephemeral Errors", "vars": []},
    {"id": "level_up_msg", "label": "Milestone Level-Up Message", "category": "Community & Lockdown", "vars": ["{user}", "{level}"]},
    {"id": "lockdown_initiated", "label": "Server Lockdown Initiated Notice", "category": "Community & Lockdown", "vars": ["{privated}", "{ignored}"]},
    {"id": "lockdown_lifted", "label": "Server Lockdown Lifted Notice", "category": "Community & Lockdown", "vars": ["{count}"]},
    {"id": "music_connected", "label": "Voice Channel Connected", "category": "Music & Audio", "vars": ["{channel}"]},
    {"id": "music_already_connected", "label": "Already Connected Alert", "category": "Music & Audio", "vars": ["{channel}"]},
    {"id": "music_moved", "label": "Moved Voice Channel Notice", "category": "Music & Audio", "vars": ["{channel}"]},
    {"id": "music_not_in_vc", "label": "User Not In Voice Channel Alert", "category": "Music & Audio", "vars": []},
    {"id": "music_bot_not_in_vc", "label": "Bot Not In Voice Channel Alert", "category": "Music & Audio", "vars": []},
    {"id": "music_disconnected", "label": "Voice Channel Disconnected", "category": "Music & Audio", "vars": []},
    {"id": "music_nothing_playing", "label": "Nothing Playing Alert", "category": "Music & Audio", "vars": []},
    {"id": "music_paused", "label": "Playback Paused Notice", "category": "Music & Audio", "vars": []},
    {"id": "music_resumed", "label": "Playback Resumed Notice", "category": "Music & Audio", "vars": []},
    {"id": "music_skipped", "label": "Track Skipped Notice", "category": "Music & Audio", "vars": []},
    {"id": "music_stopped", "label": "Playback Stopped Notice", "category": "Music & Audio", "vars": []},
    {"id": "music_queue_empty", "label": "Queue Empty Alert", "category": "Music & Audio", "vars": []},
    {"id": "ai_thinking", "label": "AI Processing / Thinking Message", "category": "AI Assistant & Conversation", "vars": ["{user}"]}
];

function initCustomResponsesControls() {
    const container = document.getElementById('customResponsesContainer');
    if (!container) return;
    
    container.innerHTML = '';
    
    // Group by category
    const categories = {};
    CUSTOM_RESPONSES_SCHEMA.forEach(cr => {
        if (!categories[cr.category]) categories[cr.category] = [];
        categories[cr.category].push(cr);
    });
    
    // Build the UI
    for (const cat in categories) {
        const catCard = document.createElement('div');
        catCard.className = 'bg-slate-800 rounded-lg p-5 border border-slate-700 h-fit';
        catCard.innerHTML = `<h3 class="text-lg font-bold text-slate-100 mb-4">${cat}</h3>`;
        
        categories[cat].forEach(cr => {
            const wrap = document.createElement('div');
            wrap.className = 'mb-4';
            
            let varsHtml = cr.vars.map(v => `<span class="bg-slate-700/50 text-slate-300 text-xs px-2 py-0.5 rounded cursor-pointer hover:bg-slate-700 transition-colors" onclick="insertCrVar('${cr.id}', '${v}')">${v}</span>`).join(' ');
            
            wrap.innerHTML = `
                <div class="flex items-center justify-between mb-1">
                    <label class="text-sm font-medium text-slate-300">${cr.label}</label>
                    <div class="flex gap-1">${varsHtml}</div>
                </div>
                <div class="relative">
                    <textarea id="cr_${cr.id}" class="w-full bg-slate-900 border border-slate-700 rounded-lg p-3 text-slate-200 focus:outline-none focus:border-blurple focus:ring-1 focus:ring-blurple transition-all text-sm resize-y min-h-[60px]" placeholder="Leave blank for default"></textarea>
                    <button type="button" class="absolute bottom-2 right-2 p-1.5 bg-slate-800 hover:bg-slate-700 rounded-md text-slate-400 hover:text-slate-200 transition-colors" onclick="openCrEmojiPicker('${cr.id}')">
                        <i data-lucide="smile" class="w-4 h-4"></i>
                    </button>
                </div>
            `;
            catCard.appendChild(wrap);
        });
        
        container.appendChild(catCard);
    }
    
    if (window.lucide) {
        lucide.createIcons();
    }
}

function insertCrVar(id, variable) {
    const input = document.getElementById(`cr_${id}`);
    if (input) {
        const start = input.selectionStart || input.value.length;
        const end = input.selectionEnd || input.value.length;
        input.value = input.value.substring(0, start) + variable + input.value.substring(end);
        input.focus();
        input.selectionStart = input.selectionEnd = start + variable.length;
    }
}

function openCrEmojiPicker(id) {
    const btn = document.querySelector(`#cr_${id}`).nextElementSibling;
    openEmojiPicker(btn, (val) => {
        const input = document.getElementById(`cr_${id}`);
        if (input) {
            const start = input.selectionStart || input.value.length;
            const end = input.selectionEnd || input.value.length;
            input.value = input.value.substring(0, start) + val + ' ' + input.value.substring(end);
            input.focus();
            input.selectionStart = input.selectionEnd = start + val.length + 1;
        }
    });
}

async function loadCustomResponsesSettings() {
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
        const autoAiInput = document.getElementById('autoAiThinkingInput');
        if (autoAiInput && (conf['ai_thinking'] !== undefined || conf['resp_ai_thinking'] !== undefined)) {
            autoAiInput.value = conf['ai_thinking'] !== undefined ? conf['ai_thinking'] : (conf['resp_ai_thinking'] || '');
        }
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
        const input = document.getElementById(`resp_${cr.id}`) || document.getElementById(`cr_${cr.id}`) || document.getElementById(cr.id);
        if (input) {
            payload[cr.id] = input.value.trim();
        }
    });

    ALL_RESPONSE_FIELDS.forEach(fieldId => {
        const key = fieldId.replace('resp_', '');
        const input = document.getElementById(fieldId);
        if (input) {
            payload[key] = input.value.trim();
        }
    });

    document.querySelectorAll('input[id^="resp_"]').forEach(input => {
        const key = input.id.replace('resp_', '');
        payload[key] = input.value.trim();
    });

    if (document.getElementById('autoAiThinkingInput')) {
        const autoVal = document.getElementById('autoAiThinkingInput').value.trim();
        if (autoVal) payload['ai_thinking'] = autoVal;
    }
    
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
}


async function saveLimits() {
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

            // Global Whitelist
            renderWhitelist('whitelistList', data.whitelist || [], 'antinuke');
            
            // Feature Whitelists (Per-feature anti-x)
            currentFeatureWhitelists = data.feature_whitelists || {};
            renderFeatureWhitelists(currentFeatureWhitelists);

            // Channels - Render Horizontally in Row
            const serverLogs = data.server_logs || {};
            const CHANNEL_SPECS = [
                { key: 'audit-antinuke', label: 'Anti-Nuke', icon: '🛡️' },
                { key: 'audit-banned', label: 'Bans', icon: '🔨' },
                { key: 'audit-timeouts', label: 'Timeouts', icon: '⏱️' },
                { key: 'audit-deleted', label: 'Deletions', icon: '🗑️' },
                { key: 'audit-roles', label: 'Roles', icon: '👑' },
                { key: 'audit-channels', label: 'Channels', icon: '📁' },
                { key: 'audit-whitelisted', label: 'Whitelist', icon: '👥' },
                { key: 'audit-abuse', label: 'Abuse', icon: '🤬' },
                { key: 'audit-antiraid', label: 'Anti-Raid', icon: '🚨' },
                { key: 'audit-antispam', label: 'Anti-Spam', icon: '💬' }
            ];

            const pillGrid = document.getElementById('secPillGrid');
            if (pillGrid) {
                pillGrid.innerHTML = '';
                let linkedCount = 0;
                CHANNEL_SPECS.forEach(spec => {
                    const isLinked = Boolean(serverLogs[spec.key]);
                    if (isLinked) linkedCount++;
                    const badge = document.createElement('div');
                    badge.className = `sec-pill-badge ${isLinked ? 'linked' : 'missing'}`;
                    badge.title = isLinked ? `Channel linked: #${serverLogs[spec.key]}` : `Channel #${spec.key} missing - click Auto-Create to link`;
                    badge.innerHTML = `
                        <span class="sec-pill-icon">${spec.icon}</span>
                        <span class="sec-pill-name">${spec.label}</span>
                        <span class="sec-pill-status">
                            <span class="sec-pill-status-dot"></span>
                            ${isLinked ? 'Linked' : 'Missing'}
                        </span>
                    `;
                    pillGrid.appendChild(badge);
                });

                const badgeEl = document.getElementById('secChannelsBadge');
                const badgeText = document.getElementById('secChannelsCountText');
                if (badgeText) {
                    badgeText.textContent = `${linkedCount}/10 Channels Active`;
                }
                if (badgeEl) {
                    if (linkedCount === 10) {
                        badgeEl.className = 'sec-channels-badge all-active';
                    } else {
                        badgeEl.className = 'sec-channels-badge';
                    }
                }
            }
        }
    } catch (e) {
        console.error("loadAntinukeSettings error:", e);
    }
}

// ───────────────────── Per-Feature Whitelist Logic (Anti-X) ─────────────────────
const ALL_SECURITY_FEATURES = [
    // Limit & Punish
    { key: 'ban', name: 'Anti Ban', icon: '🔨' },
    { key: 'kick', name: 'Anti Kick', icon: '👢' },
    { key: 'role_create', name: 'Anti Role Create', icon: '➕' },
    { key: 'role_delete', name: 'Anti Role Delete', icon: '➖' },
    { key: 'channel_create', name: 'Anti Channel Create', icon: '📁' },
    { key: 'channel_delete', name: 'Anti Channel Delete', icon: '🗑️' },
    { key: 'mention', name: 'Anti Mention Spam', icon: '📢' },
    // Instant
    { key: 'bot_add', name: 'Anti Bot Add', icon: '🤖' },
    { key: 'prune', name: 'Anti Prune', icon: '✂️' },
    { key: 'dangerous_perms', name: 'Anti Dangerous Role Permission Update', icon: '⚠️' },
    { key: 'dangerous_role_add', name: 'Anti Dangerous Role Add', icon: '👑' },
    { key: 'vanity_change', name: 'Anti Vanity Change', icon: '🔗' },
    { key: 'server_rename', name: 'Anti Server Rename', icon: '🏰' },
    { key: 'server_icon', name: 'Anti Server Icon Change', icon: '🖼️' },
    { key: 'role_rename', name: 'Anti Role Rename', icon: '🏷️' },
    { key: 'channel_rename', name: 'Anti Channel Rename', icon: '📝' },
    { key: 'emoji_delete', name: 'Anti Emoji Delete', icon: '💔' },
    { key: 'emoji_rename', name: 'Anti Emoji Rename', icon: '✏️' },
    { key: 'invite_delete', name: 'Anti Invite Delete', icon: '🗑️' }
];

let currentFeatureWhitelists = {};
let activeFeatureForPopover = null;

function renderFeatureWhitelists(fwData) {
    if (!fwData) fwData = {};
    ALL_SECURITY_FEATURES.forEach(feat => {
        const k = feat.key;
        const userIds = fwData[k] || [];

        // Count element
        const countEl = document.getElementById(`fw_count_${k}`);
        if (countEl) countEl.textContent = userIds.length;

        // Toggle button
        const btnToggle = document.getElementById(`fw_btn_${k}`);
        if (btnToggle) {
            btnToggle.style.display = userIds.length > 0 ? 'inline-flex' : 'none';
        }

        // List in drawer
        const listEl = document.getElementById(`fw_list_${k}`);
        const drawerEl = document.getElementById(`fw_drawer_${k}`);
        if (listEl) {
            listEl.innerHTML = '';
            if (userIds.length === 0) {
                listEl.innerHTML = `<span style="font-size: 11px; color: var(--text-muted); font-style: italic;">No members whitelisted specifically for this feature. Click <b>+</b> to exempt a member.</span>`;
                if (drawerEl) drawerEl.style.display = 'none';
                if (btnToggle) btnToggle.classList.remove('open');
            } else {
                userIds.forEach(item => {
                    const uid = typeof item === 'object' && item !== null ? item.id : item;
                    const itemUsername = typeof item === 'object' && item !== null ? item.username : null;
                    const itemAvatar = typeof item === 'object' && item !== null ? item.avatar : null;
                    const member = currentGuildMembers.find(m => String(m.id) === String(uid));
                    const username = member ? member.username : (itemUsername || `User ${uid}`);
                    const avatar = member && member.avatar ? member.avatar : itemAvatar;
                    const avatarHtml = avatar ? `<img src="${avatar}" alt="" class="fw-chip-avatar">` : `<div class="fw-chip-avatar-fallback">${username.charAt(0).toUpperCase()}</div>`;

                    const chip = document.createElement('div');
                    chip.className = 'fw-member-chip';
                    chip.innerHTML = `
                        ${avatarHtml}
                        <span class="fw-chip-name">${escapeHtml(username)}</span>
                        <span class="fw-chip-id">${uid}</span>
                        <button class="fw-chip-remove" type="button" title="Remove whitelist for ${escapeHtml(username)}">&times;</button>
                    `;
                    chip.querySelector('.fw-chip-remove').addEventListener('click', (e) => {
                        e.stopPropagation();
                        removeFeatureWhitelistUser(k, uid, username);
                    });
                    listEl.appendChild(chip);
                });
            }
        }
    });
}

function toggleFeatureDrawer(featureKey) {
    const drawer = document.getElementById(`fw_drawer_${featureKey}`);
    const btn = document.getElementById(`fw_btn_${featureKey}`);
    if (!drawer) return;
    const isClosed = drawer.style.display === 'none' || !drawer.style.display;
    drawer.style.display = isClosed ? 'block' : 'none';
    if (btn) btn.classList.toggle('open', isClosed);
}

function openFeatureWhitelistPopover(featureKey, buttonEl) {
    if (!currentGuildId) return showToast("⚠️ Select a server first!");
    activeFeatureForPopover = featureKey;
    const featObj = ALL_SECURITY_FEATURES.find(f => f.key === featureKey);
    const titleEl = document.getElementById('featWlPopoverTitle');
    if (titleEl) {
        titleEl.textContent = `Whitelist: ${featObj ? featObj.name : featureKey}`;
    }

    const popover = document.getElementById('featWlPopover');
    const searchInput = document.getElementById('featWlSearchInput');
    if (!popover) return;

    // Position popover relative to button
    const rect = buttonEl.getBoundingClientRect();
    popover.style.display = 'block';

    const popWidth = 320;
    let left = rect.left;
    if (left + popWidth > window.innerWidth - 16) {
        left = window.innerWidth - popWidth - 16;
    }
    if (left < 16) left = 16;

    let top = rect.bottom + 8;
    if (top + 340 > window.innerHeight) {
        top = Math.max(16, rect.top - 340);
    }

    popover.style.left = `${left}px`;
    popover.style.top = `${top}px`;

    if (searchInput) {
        searchInput.value = '';
        setTimeout(() => searchInput.focus(), 60);
    }

    renderFeaturePopoverMembers('');
}

function closeFeatureWhitelistPopover() {
    const popover = document.getElementById('featWlPopover');
    if (popover) popover.style.display = 'none';
    activeFeatureForPopover = null;
}

function renderFeaturePopoverMembers(query) {
    const listEl = document.getElementById('featWlMemberList');
    if (!listEl) return;
    listEl.innerHTML = '';

    const q = (query || '').toLowerCase().trim();
    const currentList = (currentFeatureWhitelists[activeFeatureForPopover] || []).map(x => typeof x === 'object' && x !== null ? String(x.id) : String(x));

    const filtered = currentGuildMembers.filter(m => {
        const matchesQuery = !q || m.username.toLowerCase().includes(q) || String(m.id).includes(q);
        const notAlreadyAdded = !currentList.includes(String(m.id));
        return matchesQuery && notAlreadyAdded;
    });

    if (filtered.length === 0) {
        listEl.innerHTML = `<div style="padding: 16px; text-align: center; color: var(--text-muted); font-size: 12px;">No eligible members found</div>`;
        return;
    }

    filtered.slice(0, 30).forEach(m => {
        const item = document.createElement('div');
        item.className = 'fw-popover-item';
        const avatarHtml = m.avatar ? `<img src="${m.avatar}" alt="" class="fw-popover-avatar">` : `<div class="fw-popover-avatar-fallback">${m.username.charAt(0).toUpperCase()}</div>`;
        item.innerHTML = `
            ${avatarHtml}
            <div class="fw-popover-user-info">
                <span class="fw-popover-username">${escapeHtml(m.username)}</span>
                <span class="fw-popover-userid">${m.id}</span>
            </div>
            <button class="fw-popover-add-btn" type="button">Select</button>
        `;
        item.addEventListener('click', () => {
            addFeatureWhitelistUser(activeFeatureForPopover, m.id, m.username);
        });
        listEl.appendChild(item);
    });
}

async function addFeatureWhitelistUser(featureKey, userId, username) {
    try {
        const resp = await fetch(`/api/guild/${currentGuildId}/security/feature_whitelist/add`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ feature: featureKey, user_id: userId })
        });
        const data = await resp.json();
        if (data.success) {
            if (!currentFeatureWhitelists[featureKey]) currentFeatureWhitelists[featureKey] = [];
            const alreadyPresent = currentFeatureWhitelists[featureKey].some(x => {
                const id = typeof x === 'object' && x !== null ? x.id : x;
                return String(id) === String(userId);
            });
            if (!alreadyPresent) {
                currentFeatureWhitelists[featureKey].push(data.user || { id: String(userId), username: username });
            }
            renderFeatureWhitelists(currentFeatureWhitelists);

            // Expand drawer so user sees newly whitelisted member
            const drawer = document.getElementById(`fw_drawer_${featureKey}`);
            const btn = document.getElementById(`fw_btn_${featureKey}`);
            if (drawer) drawer.style.display = 'block';
            if (btn) btn.classList.add('open');

            closeFeatureWhitelistPopover();
            const featObj = ALL_SECURITY_FEATURES.find(f => f.key === featureKey);
            showToast(`🛡️ Whitelisted @${username} for ${featObj ? featObj.name : featureKey}`);
        } else {
            showToast(`❌ Error: ${data.error || 'Failed to add'}`);
        }
    } catch (e) {
        showToast("❌ Network error adding whitelisted member");
    }
}

async function removeFeatureWhitelistUser(featureKey, userId, username) {
    try {
        const resp = await fetch(`/api/guild/${currentGuildId}/security/feature_whitelist/remove`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ feature: featureKey, user_id: userId })
        });
        const data = await resp.json();
        if (data.success) {
            if (currentFeatureWhitelists[featureKey]) {
                currentFeatureWhitelists[featureKey] = currentFeatureWhitelists[featureKey].filter(x => {
                    const id = typeof x === 'object' && x !== null ? x.id : x;
                    return String(id) !== String(userId);
                });
            }
            renderFeatureWhitelists(currentFeatureWhitelists);
            const featObj = ALL_SECURITY_FEATURES.find(f => f.key === featureKey);
            showToast(`Removed @${username} from ${featObj ? featObj.name : featureKey}`);
        } else {
            showToast(`❌ Error: ${data.error || 'Failed to remove'}`);
        }
    } catch (e) {
        showToast("❌ Network error removing whitelisted member");
    }
}

function setupFeatureWhitelistEvents() {
    const section = document.getElementById('antinukeSection');
    if (!section) return;

    // Delegation for clicking "+" add button, toggle drawer button, or feature name
    section.addEventListener('click', (e) => {
        const addBtn = e.target.closest('.btn-fw-add');
        if (addBtn) {
            e.preventDefault();
            e.stopPropagation();
            const feat = addBtn.dataset.feature;
            if (feat) openFeatureWhitelistPopover(feat, addBtn);
            return;
        }

        const toggleBtn = e.target.closest('.btn-fw-toggle');
        if (toggleBtn) {
            e.preventDefault();
            e.stopPropagation();
            const feat = toggleBtn.dataset.feature;
            if (feat) toggleFeatureDrawer(feat);
            return;
        }

        const clickableName = e.target.closest('.sec-name.clickable-name');
        if (clickableName) {
            e.preventDefault();
            e.stopPropagation();
            const feat = clickableName.dataset.feature;
            if (feat) toggleFeatureDrawer(feat);
            return;
        }
    });

    // Popover close button
    const closeBtn = document.getElementById('featWlPopoverClose');
    if (closeBtn) {
        closeBtn.addEventListener('click', (e) => {
            e.stopPropagation();
            closeFeatureWhitelistPopover();
        });
    }

    // Search input typing
    const searchInput = document.getElementById('featWlSearchInput');
    if (searchInput) {
        searchInput.addEventListener('input', (e) => {
            renderFeaturePopoverMembers(e.target.value);
        });
        searchInput.addEventListener('keydown', (e) => {
            if (e.key === 'Escape') {
                closeFeatureWhitelistPopover();
            }
        });
    }

    // Clicking outside closes popover
    document.addEventListener('click', (e) => {
        const popover = document.getElementById('featWlPopover');
        if (popover && popover.style.display !== 'none') {
            if (!popover.contains(e.target) && !e.target.closest('.btn-fw-add')) {
                closeFeatureWhitelistPopover();
            }
        }
    });

    // Escape closes popover
    document.addEventListener('keydown', (e) => {
        if (e.key === 'Escape') {
            closeFeatureWhitelistPopover();
        }
    });
}


// ───────────────────── Module 8: Automations (Auto Mentions) Logic ─────────────────────
let currentAutoreactRules = [];
let currentAutoresponderRules = [];
let currentAutoresponderIgnoredChannels = [];

async function loadAutomationsSettings() {
    if (!currentGuildId) return;
    try {
        const resp = await fetch(`/api/guild/${currentGuildId}/automations`);
        const data = await resp.json();
        if (data.success) {
            currentAutoreactRules = data.autoreact || [];
            const arData = data.autoresponder || {};
            currentAutoresponderRules = arData.rules || [];
            currentAutoresponderIgnoredChannels = (arData.ignored_channels || []).map(String);

            renderAutoReactRules();
            renderAutoResponderRules();
            renderIgnoredChannels();

            try {
                const crResp = await fetch(`/api/guild/${currentGuildId}/custom_responses`);
                const crData = await crResp.json();
                const crConf = crData.config || crData || {};
                const autoAiInput = document.getElementById('autoAiThinkingInput');
                if (autoAiInput && crConf['ai_thinking'] !== undefined) {
                    autoAiInput.value = crConf['ai_thinking'];
                }
            } catch (err) {}
        }
    } catch (e) {
        console.error("Failed to load automations", e);
    }
}

function renderAutoReactRules() {
    const listEl = document.getElementById('autoReactRulesList');
    const countEl = document.getElementById('autoReactCount');
    if (!listEl) return;
    if (countEl) countEl.textContent = currentAutoreactRules.length;

    if (currentAutoreactRules.length === 0) {
        listEl.innerHTML = '<div class="empty-rules-placeholder">No auto-react rules configured yet.</div>';
        return;
    }

    listEl.innerHTML = '';
    currentAutoreactRules.forEach(rule => {
        const member = currentGuildMembers.find(m => String(m.id) === String(rule.user_id));
        const username = member ? member.username : (rule.user_name || `User ${rule.user_id}`);
        const avatar = member ? member.avatar : null;
        const avatarHtml = avatar ? `<img src="${avatar}" alt="" class="automation-rule-avatar">` : `<div class="automation-rule-avatar-fallback">${username.charAt(0).toUpperCase()}</div>`;

        const item = document.createElement('div');
        item.className = 'automation-rule-item';
        item.innerHTML = `
            <div class="automation-rule-user">
                ${avatarHtml}
                <div class="automation-rule-meta">
                    <span class="automation-rule-name">${escapeHtml(username)}</span>
                    <span class="automation-rule-id">${rule.user_id}</span>
                </div>
            </div>
            <div class="automation-rule-badge" style="display:inline-flex; align-items:center; justify-content:center; min-width:32px; height:32px; padding:2px 8px; background:rgba(255,255,255,0.06); border:1px solid var(--border-subtle); border-radius:6px;">
                ${renderEmojiHtmlOrChar(rule.emoji, 24)}
            </div>
            <button class="btn-delete-rule" title="Remove rule" type="button" data-user="${rule.user_id}">
                <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polyline points="3 6 5 6 21 6"></polyline><path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6m3 0V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2"></path></svg>
            </button>
        `;

        item.querySelector('.btn-delete-rule').addEventListener('click', () => {
            removeAutoReactRule(rule.user_id);
        });

        listEl.appendChild(item);
    });
}

function renderAutoResponderRules() {
    const listEl = document.getElementById('autoRespRulesList');
    const countEl = document.getElementById('autoRespCount');
    if (!listEl) return;
    if (countEl) countEl.textContent = currentAutoresponderRules.length;

    if (currentAutoresponderRules.length === 0) {
        listEl.innerHTML = '<div class="empty-rules-placeholder">No auto-responder rules configured yet.</div>';
        return;
    }

    listEl.innerHTML = '';
    currentAutoresponderRules.forEach(rule => {
        const member = currentGuildMembers.find(m => String(m.id) === String(rule.user_id));
        const username = member ? member.username : (rule.user_name || `User ${rule.user_id}`);
        const avatar = member ? member.avatar : null;
        const avatarHtml = avatar ? `<img src="${avatar}" alt="" class="automation-rule-avatar">` : `<div class="automation-rule-avatar-fallback">${username.charAt(0).toUpperCase()}</div>`;

        const item = document.createElement('div');
        item.className = 'automation-rule-item';
        item.innerHTML = `
            <div class="automation-rule-user">
                ${avatarHtml}
                <div class="automation-rule-meta">
                    <span class="automation-rule-name">${escapeHtml(username)}</span>
                    <span class="automation-rule-id">${rule.user_id}</span>
                </div>
            </div>
            <div class="automation-rule-content" title="${escapeHtml(rule.response)}">
                ${renderDiscordMarkdown(rule.response)}
            </div>
            <button class="btn-delete-rule" title="Remove rule" type="button" data-user="${rule.user_id}">
                <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polyline points="3 6 5 6 21 6"></polyline><path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6m3 0V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2"></path></svg>
            </button>
        `;

        item.querySelector('.btn-delete-rule').addEventListener('click', () => {
            removeAutoResponderRule(rule.user_id);
        });

        listEl.appendChild(item);
    });
}

function renderIgnoredChannels() {
    const listEl = document.getElementById('autoRespIgnoredChipsList');
    const countEl = document.getElementById('autoRespIgnoredCount');
    if (!listEl) return;
    if (countEl) countEl.textContent = currentAutoresponderIgnoredChannels.length;

    if (currentAutoresponderIgnoredChannels.length === 0) {
        listEl.innerHTML = '<div class="empty-rules-placeholder">No channels ignored. Auto-responder operates server-wide.</div>';
        return;
    }

    listEl.innerHTML = '';
    currentAutoresponderIgnoredChannels.forEach(chanId => {
        const chan = currentGuildChannels.find(c => String(c.id) === String(chanId));
        const chanName = chan ? chan.name : `channel-${chanId}`;

        const chip = document.createElement('div');
        chip.className = 'channel-chip-tag';
        chip.innerHTML = `
            <span># ${escapeHtml(chanName)}</span>
            <button class="channel-chip-remove" title="Unignore channel" type="button" data-chan="${chanId}">&times;</button>
        `;

        chip.querySelector('.channel-chip-remove').addEventListener('click', () => {
            removeIgnoredChannel(chanId);
        });

        listEl.appendChild(chip);
    });
}

async function addAutoReactRule() {
    if (!currentGuildId) return showToast("⚠️ Select a server first!");
    const memberSelect = document.getElementById('autoReactMemberSelect');
    const emojiInput = document.getElementById('autoReactEmojiInput');
    const userId = memberSelect ? memberSelect.value : '';
    const emoji = emojiInput ? (emojiInput.dataset.rawEmoji || emojiInput.value).trim() : '';

    if (!userId) return showToast("⚠️ Please select a target member!");
    if (!emoji) return showToast("⚠️ Please choose a reaction emoji!");

    const member = currentGuildMembers.find(m => String(m.id) === String(userId));
    const userName = member ? member.username : `User ${userId}`;

    try {
        const resp = await fetch(`/api/guild/${currentGuildId}/autoreact/add`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ user_id: userId, user_name: userName, emoji: emoji })
        });
        const data = await resp.json();
        if (data.success) {
            currentAutoreactRules = data.autoreact || [];
            renderAutoReactRules();
            showToast("✅ Auto-react rule saved!");
            if (emojiInput) {
                emojiInput.value = '';
                emojiInput.dataset.rawEmoji = '';
            }
            const arEmojiBtn = document.getElementById('autoReactEmojiBtn');
            if (arEmojiBtn) arEmojiBtn.textContent = '😊';
            if (memberSelect) memberSelect.value = '';
        } else {
            showToast(`❌ Error: ${data.error || 'Failed to add rule'}`);
        }
    } catch (e) {
        showToast("❌ Network error adding auto-react rule");
    }
}

async function removeAutoReactRule(userId) {
    if (!currentGuildId) return;
    try {
        const resp = await fetch(`/api/guild/${currentGuildId}/autoreact/remove`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ user_id: userId })
        });
        const data = await resp.json();
        if (data.success) {
            currentAutoreactRules = data.autoreact || [];
            renderAutoReactRules();
            showToast("🗑️ Auto-react rule removed.");
        }
    } catch (e) {
        showToast("❌ Failed to remove rule");
    }
}

async function addAutoResponderRule() {
    if (!currentGuildId) return showToast("⚠️ Select a server first!");
    const memberSelect = document.getElementById('autoRespMemberSelect');
    const textInput = document.getElementById('autoRespTextInput');
    const userId = memberSelect ? memberSelect.value : '';
    const responseText = textInput ? textInput.value.trim() : '';

    if (!userId) return showToast("⚠️ Please select a target member!");
    if (!responseText) return showToast("⚠️ Please enter a response message!");

    const member = currentGuildMembers.find(m => String(m.id) === String(userId));
    const userName = member ? member.username : `User ${userId}`;

    try {
        const resp = await fetch(`/api/guild/${currentGuildId}/autoresponder/add`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ user_id: userId, user_name: userName, response: responseText })
        });
        const data = await resp.json();
        if (data.success) {
            currentAutoresponderRules = (data.autoresponder && data.autoresponder.rules) || [];
            renderAutoResponderRules();
            showToast("✅ Auto-responder rule saved!");
            if (textInput) textInput.value = '';
            if (memberSelect) memberSelect.value = '';
        } else {
            showToast(`❌ Error: ${data.error || 'Failed to add rule'}`);
        }
    } catch (e) {
        showToast("❌ Network error adding auto-responder rule");
    }
}

async function removeAutoResponderRule(userId) {
    if (!currentGuildId) return;
    try {
        const resp = await fetch(`/api/guild/${currentGuildId}/autoresponder/remove`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ user_id: userId })
        });
        const data = await resp.json();
        if (data.success) {
            currentAutoresponderRules = (data.autoresponder && data.autoresponder.rules) || [];
            renderAutoResponderRules();
            showToast("🗑️ Auto-responder rule removed.");
        }
    } catch (e) {
        showToast("❌ Failed to remove rule");
    }
}

async function addAutoRespIgnoredChannel() {
    if (!currentGuildId) return showToast("⚠️ Select a server first!");
    const chanSelect = document.getElementById('autoRespIgnoreChannelSelect');
    const channelId = chanSelect ? chanSelect.value : '';
    if (!channelId) return showToast("⚠️ Please select a channel to ignore!");

    try {
        const resp = await fetch(`/api/guild/${currentGuildId}/autoresponder/ignore_channel`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ channel_id: channelId })
        });
        const data = await resp.json();
        if (data.success) {
            currentAutoresponderIgnoredChannels = (data.autoresponder && data.autoresponder.ignored_channels) || [];
            renderIgnoredChannels();
            showToast("✅ Channel added to ignore list!");
            if (chanSelect) chanSelect.value = '';
        } else {
            showToast(`❌ Error: ${data.error || 'Failed to ignore channel'}`);
        }
    } catch (e) {
        showToast("❌ Network error adding ignored channel");
    }
}

async function removeIgnoredChannel(channelId) {
    if (!currentGuildId) return;
    try {
        const resp = await fetch(`/api/guild/${currentGuildId}/autoresponder/unignore_channel`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ channel_id: channelId })
        });
        const data = await resp.json();
        if (data.success) {
            currentAutoresponderIgnoredChannels = (data.autoresponder && data.autoresponder.ignored_channels) || [];
            renderIgnoredChannels();
            showToast("🗑️ Channel removed from ignore list.");
        }
    } catch (e) {
        showToast("❌ Failed to remove channel");
    }
}

function setupAutomationEvents() {
    const arEmojiBtn = document.getElementById('autoReactEmojiBtn');
    const arEmojiInput = document.getElementById('autoReactEmojiInput');

    const triggerArPicker = (e) => {
        if (e) {
            e.preventDefault();
            e.stopPropagation();
        }
        openEmojiPicker(arEmojiBtn || arEmojiInput, (emojiVal) => {
            if (!emojiVal) return;
            if (arEmojiInput) {
                arEmojiInput.dataset.rawEmoji = emojiVal;
                const m = emojiVal.match(/<a?:([a-zA-Z0-9_]+):[0-9]+>/);
                arEmojiInput.value = m ? `:${m[1]}:` : emojiVal;
            }
            if (arEmojiBtn) {
                arEmojiBtn.innerHTML = renderEmojiHtmlOrChar(emojiVal, 22);
            }
        });
    };

    if (arEmojiBtn) arEmojiBtn.addEventListener('click', triggerArPicker);
    if (arEmojiInput) {
        arEmojiInput.style.cursor = 'pointer';
        arEmojiInput.addEventListener('click', triggerArPicker);
        arEmojiInput.addEventListener('input', (e) => {
            const val = e.target.value.trim();
            if (arEmojiBtn) arEmojiBtn.innerHTML = renderEmojiHtmlOrChar(val, 22);
        });
    }

    const addArBtn = document.getElementById('addAutoReactBtn');
    if (addArBtn) addArBtn.addEventListener('click', addAutoReactRule);

    const addRespBtn = document.getElementById('addAutoRespBtn');
    if (addRespBtn) addRespBtn.addEventListener('click', addAutoResponderRule);

    const addIgnBtn = document.getElementById('addIgnoreChannelBtn');
    if (addIgnBtn) addIgnBtn.addEventListener('click', addAutoRespIgnoredChannel);
}

// Hook setupAutomationEvents on DOMContentLoaded
document.addEventListener('DOMContentLoaded', () => {
    setupAutomationEvents();
    setupFirstWelcomeAndAfkEvents();
});

// ───────────────────── MODULE 9: FIRST CHAT WELCOME ─────────────────────
let currentFwColor = "#10b981";

async function loadFirstWelcomeSettings() {
    if (!currentGuildId) return;
    try {
        const resp = await fetch(`/api/guild/${currentGuildId}/first_welcome`);
        const data = await resp.json();
        if (data.success && data.config) {
            const cfg = data.config;
            const tgl = document.getElementById('firstWelcomeToggle');
            if (tgl) tgl.checked = !!cfg.enabled;

            const chanSelect = document.getElementById('firstWelcomeChannelSelect');
            if (chanSelect && cfg.channel_id) chanSelect.value = cfg.channel_id;

            const titleInput = document.getElementById('firstWelcomeTitleInput');
            if (titleInput) titleInput.value = cfg.title || "WELCOME TO {server}";

            const msgInput = document.getElementById('firstWelcomeMsgInput');
            if (msgInput) msgInput.value = cfg.message || "Welcome to **{server}**, {user}! We are thrilled to have you here. Feel free to introduce yourself and make yourself at home! 💫";

            const avtTgl = document.getElementById('firstWelcomeAvatarToggle');
            if (avtTgl) avtTgl.checked = cfg.show_avatar !== false;

            const color = cfg.custom_hex || "#10b981";
            setFirstWelcomeColor(color);
            updateFirstWelcomePreview();
        }
    } catch (e) {
        console.error("Error loading first welcome settings:", e);
    }
}

function setFirstWelcomeColor(hex) {
    currentFwColor = hex;
    const picker = document.getElementById('firstWelcomeColorPicker');
    if (picker) picker.value = hex;
    const hexInput = document.getElementById('firstWelcomeHexInput');
    if (hexInput) hexInput.value = hex;

    document.querySelectorAll('.fw-color-btn').forEach(btn => {
        if (btn.dataset.color && btn.dataset.color.toLowerCase() === hex.toLowerCase()) {
            btn.style.borderColor = '#ffffff';
            btn.classList.add('active');
        } else {
            btn.style.borderColor = 'transparent';
            btn.classList.remove('active');
        }
    });

    updateFirstWelcomePreview();
}

function updateFirstWelcomePreview() {
    const titleInput = document.getElementById('firstWelcomeTitleInput');
    const msgInput = document.getElementById('firstWelcomeMsgInput');
    const avtTgl = document.getElementById('firstWelcomeAvatarToggle');
    const simEmbed = document.getElementById('fwSimEmbed');
    const simTitle = document.getElementById('fwSimTitle');
    const simMsg = document.getElementById('fwSimMsg');
    const simThumbnail = document.getElementById('fwSimThumbnail');

    if (simEmbed) {
        simEmbed.style.borderLeftColor = currentFwColor;
    }

    const guildName = (guildNameDisplay && guildNameDisplay.textContent !== "Select a server...") 
        ? guildNameDisplay.textContent 
        : "Our Community";

    if (simTitle && titleInput) {
        let t = titleInput.value || "WELCOME TO {server}";
        t = t.replace(/{server}/g, guildName).replace(/{username}/g, "Alex").replace(/{user}/g, "@Alex");
        simTitle.innerHTML = renderDiscordMarkdown(`✓ ${t}`);
    }

    if (simMsg && msgInput) {
        let m = msgInput.value || "Welcome to **{server}**, {user}!";
        m = m.replace(/{server}/g, guildName)
             .replace(/{username}/g, "Alex")
             .replace(/{user}/g, "@Alex")
             .replace(/{name}/g, "Alex")
             .replace(/{member_count}/g, "1,420")
             .replace(/{channel}/g, "#general");
        simMsg.innerHTML = renderDiscordMarkdown(m);
    }

    if (simThumbnail && avtTgl) {
        simThumbnail.style.display = avtTgl.checked ? "flex" : "none";
    }
}

async function saveFirstWelcomeSettings() {
    if (!currentGuildId) return showToast("⚠️ Select a server first!");

    const tgl = document.getElementById('firstWelcomeToggle');
    const chanSelect = document.getElementById('firstWelcomeChannelSelect');
    const titleInput = document.getElementById('firstWelcomeTitleInput');
    const msgInput = document.getElementById('firstWelcomeMsgInput');
    const avtTgl = document.getElementById('firstWelcomeAvatarToggle');

    const payload = {
        enabled: tgl ? tgl.checked : false,
        channel_id: chanSelect ? (chanSelect.value || null) : null,
        title: titleInput ? titleInput.value : "WELCOME TO {server}",
        message: msgInput ? msgInput.value : "Welcome to **{server}**, {user}!",
        show_avatar: avtTgl ? avtTgl.checked : true,
        custom_hex: currentFwColor,
        status_color: "success"
    };

    try {
        const resp = await fetch(`/api/guild/${currentGuildId}/first_welcome/update`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(payload)
        });
        const data = await resp.json();
        if (data.success) {
            showToast("✅ First Welcome settings saved successfully!");
        } else {
            showToast(`❌ Error: ${data.error || 'Failed to save'}`);
        }
    } catch (e) {
        showToast("❌ Network error saving settings");
    }
}

async function sendTestFirstWelcome() {
    if (!currentGuildId) return showToast("⚠️ Select a server first!");

    try {
        showToast("🚀 Sending test welcome card to Discord...");
        const resp = await fetch(`/api/guild/${currentGuildId}/first_welcome/test`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' }
        });
        const data = await resp.json();
        if (data.success) {
            showToast(`✅ Test card sent to #${data.channel_name}!`);
        } else {
            showToast(`❌ Test failed: ${data.error || 'Check bot permissions'}`);
        }
    } catch (e) {
        showToast("❌ Network error sending test card");
    }
}

// ───────────────────── MODULE 10: AFK SYSTEM & PING TRACKER ─────────────────────

async function loadAfkSettings() {
    if (!currentGuildId) return;
    try {
        const resp = await fetch(`/api/guild/${currentGuildId}/afk`);
        const data = await resp.json();
        const listContainer = document.getElementById('afkMembersList');
        const countSpan = document.getElementById('afkActiveCount');

        if (data.success && Array.isArray(data.afk_members)) {
            const members = data.afk_members;
            if (countSpan) countSpan.textContent = members.length;

            if (!listContainer) return;

            if (members.length === 0) {
                listContainer.innerHTML = '<div class="empty-rules-placeholder">No members are currently AFK in this server.</div>';
                return;
            }

            listContainer.innerHTML = members.map(m => {
                const avatarImg = m.avatar 
                    ? `<img src="${m.avatar}" style="width: 38px; height: 38px; border-radius: 50%; object-fit: cover;">`
                    : `<div style="width: 38px; height: 38px; border-radius: 50%; background: #2b2d31; display: flex; align-items: center; justify-content: center; font-weight: 700; color: #fff;">${escapeHtml(m.username.charAt(0).toUpperCase())}</div>`;
                
                return `
                    <div style="display: flex; justify-content: space-between; align-items: center; background: rgba(255,255,255,0.03); border: 1px solid var(--border-subtle); border-radius: 8px; padding: 12px 16px;">
                        <div style="display: flex; align-items: center; gap: 12px;">
                            ${avatarImg}
                            <div>
                                <div style="display: flex; align-items: center; gap: 8px;">
                                    <span style="font-weight: 700; font-size: 14px; color: var(--text-primary);">${escapeHtml(m.username)}</span>
                                    <span style="font-size: 11px; background: rgba(99, 102, 241, 0.15); color: #818cf8; border-radius: 4px; padding: 2px 6px; font-weight: 600;">AFK ${escapeHtml(m.duration)}</span>
                                    ${m.mentions_count > 0 ? `<span style="font-size: 11px; background: rgba(245, 158, 11, 0.15); color: #fbbf24; border-radius: 4px; padding: 2px 6px; font-weight: 600;">📬 ${m.mentions_count} pings</span>` : ''}
                                </div>
                                <div style="font-size: 12px; color: var(--text-muted); margin-top: 3px;">
                                    Reason: <span style="color: var(--text-secondary); font-style: italic;">"${escapeHtml(m.reason)}"</span>
                                </div>
                            </div>
                        </div>
                        <button type="button" class="btn-clear-afk" onclick="clearAfkStatus('${m.user_id}')" style="background: rgba(239, 68, 68, 0.12); color: #ef4444; border: 1px solid rgba(239, 68, 68, 0.3); border-radius: 6px; padding: 6px 12px; font-size: 12px; font-weight: 600; cursor: pointer; display: flex; align-items: center; gap: 6px; transition: all 0.2s ease;">
                            <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"><line x1="18" y1="6" x2="6" y2="18"></line><line x1="6" y1="6" x2="18" y2="18"></line></svg>
                            Clear AFK
                        </button>
                    </div>
                `;
            }).join('');
        }
    } catch (e) {
        console.error("Error loading AFK data:", e);
    }
}

async function clearAfkStatus(userId) {
    if (!currentGuildId || !userId) return;
    try {
        const resp = await fetch(`/api/guild/${currentGuildId}/afk/clear`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ user_id: userId })
        });
        const data = await resp.json();
        if (data.success) {
            showToast("✅ Member AFK status cleared.");
            await loadAfkSettings();
        } else {
            showToast(`❌ Error: ${data.error || 'Failed to clear'}`);
        }
    } catch (e) {
        showToast("❌ Network error clearing AFK");
    }
}

function setupFirstWelcomeAndAfkEvents() {
    // Inputs live simulator listeners
    const titleInput = document.getElementById('firstWelcomeTitleInput');
    if (titleInput) titleInput.addEventListener('input', updateFirstWelcomePreview);

    const titleEmojiBtn = document.getElementById('firstWelcomeTitleEmojiBtn');
    if (titleEmojiBtn && titleInput) {
        titleEmojiBtn.addEventListener('click', (e) => {
            e.preventDefault();
            e.stopPropagation();
            openEmojiPicker(titleEmojiBtn, (emojiVal) => {
                if (!emojiVal) return;
                const start = titleInput.selectionStart ?? titleInput.value.length;
                const end = titleInput.selectionEnd ?? titleInput.value.length;
                titleInput.value = titleInput.value.substring(0, start) + emojiVal + ' ' + titleInput.value.substring(end);
                titleInput.focus();
                titleInput.selectionStart = titleInput.selectionEnd = start + emojiVal.length + 1;
                titleEmojiBtn.innerHTML = renderEmojiHtmlOrChar(emojiVal, 20);
                updateFirstWelcomePreview();
            });
        });
    }

    const msgInput = document.getElementById('firstWelcomeMsgInput');
    if (msgInput) msgInput.addEventListener('input', updateFirstWelcomePreview);

    const msgEmojiBtn = document.getElementById('firstWelcomeMsgEmojiBtn');
    if (msgEmojiBtn && msgInput) {
        msgEmojiBtn.addEventListener('click', (e) => {
            e.preventDefault();
            e.stopPropagation();
            openEmojiPicker(msgEmojiBtn, (emojiVal) => {
                if (!emojiVal) return;
                const start = msgInput.selectionStart ?? msgInput.value.length;
                const end = msgInput.selectionEnd ?? msgInput.value.length;
                msgInput.value = msgInput.value.substring(0, start) + emojiVal + ' ' + msgInput.value.substring(end);
                msgInput.focus();
                msgInput.selectionStart = msgInput.selectionEnd = start + emojiVal.length + 1;
                updateFirstWelcomePreview();
            });
        });
    }

    const avtTgl = document.getElementById('firstWelcomeAvatarToggle');
    if (avtTgl) avtTgl.addEventListener('change', updateFirstWelcomePreview);

    const colorPicker = document.getElementById('firstWelcomeColorPicker');
    if (colorPicker) {
        colorPicker.addEventListener('input', (e) => setFirstWelcomeColor(e.target.value));
    }

    const hexInput = document.getElementById('firstWelcomeHexInput');
    if (hexInput) {
        hexInput.addEventListener('input', (e) => {
            const val = e.target.value.trim();
            if (/^#[0-9A-Fa-f]{6}$/.test(val)) {
                setFirstWelcomeColor(val);
            }
        });
    }

    document.querySelectorAll('.fw-color-btn').forEach(btn => {
        btn.addEventListener('click', () => setFirstWelcomeColor(btn.dataset.color));
    });

    const saveFwBtn = document.getElementById('saveFirstWelcomeBtn');
    if (saveFwBtn) saveFwBtn.addEventListener('click', saveFirstWelcomeSettings);

    const testFwBtn = document.getElementById('testFirstWelcomeBtn');
    if (testFwBtn) testFwBtn.addEventListener('click', sendTestFirstWelcome);

    const refreshAfkBtn = document.getElementById('refreshAfkBtn');
    if (refreshAfkBtn) refreshAfkBtn.addEventListener('click', () => {
        loadAfkSettings();
        showToast("🔄 AFK list refreshed.");
    });
}
