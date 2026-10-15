import json
import os
import random
import discord

JOKES_FILE = os.path.join(os.path.dirname(__file__), "data", "hinglish_jokes.json")

# Fallback default jokes in case file is absent
DEFAULT_JOKES = [
    {
        "category": "student",
        "title": "🎓 College Viva Ka Khauf",
        "setup": "External Examiner: 'Batao, Ohm's Law kya hota hai?'",
        "punchline": "Engineering Student: 'Sir, jo Ohm bolta hai wo uska Law hota hai... hum beech me bolne wale kaun hote hain!'\nExaminer: 'Viva se bahar nikal, zero le aur dubara mat dikhna!'"
    },
    {
        "category": "desi_family",
        "title": "🏠 Sharma Ji Ka Beta",
        "setup": "Papa: 'Sharma ji ke ladke ko dekha? 99% laaya hai board me!'",
        "punchline": "Beta: 'Haan papa, aur Sharma ji ko dekha? Uske 99% aane pe use iPhone aur Dubai trip dilayi... aap kab leke chal rahe ho?'\n*Flying Chappal detected at Mach 3 speed.*"
    },
    {
        "category": "corporate",
        "title": "💼 HR Ka Interview",
        "setup": "HR: 'Aapki sabse badi strength kya hai?'",
        "punchline": "Candidate: 'Main bina kaam kiye laptop screen ghoorta reh sakta hoon aur sabko lagta hai main deep code review kar raha hoon!'\nHR: 'Welcome to the team! Team Lead banoge aap!'"
    },
    {
        "category": "classics",
        "title": "🎅 Santa Petrol Pump Par",
        "setup": "Santa petrol pump pe gaya aur bola: 'Bhaiya 10 rupaye ka petrol daal do.'\nAttendant: 'Bhai itne me to bike start bhi nahi hogi!'",
        "punchline": "Santa: 'Arey chalani kisko hai, bas bike pe chhidak ke smell leni hai taaki mohalle me lage gaadi se aaya hoon!'"
    },
    {
        "category": "dating",
        "title": "❤️ Remote Control Boyfriend",
        "setup": "Ladki: 'Mujhe aisa ladka chahiye jo smart ho, loyal ho, handsome ho aur meri har baat maane bina kisi sawal ke!'",
        "punchline": "Ladka: 'Didi use ladka nahi bolte... use battery wala khilona bolte hain, D-Mart me 200 rupaye me mil jayega!'"
    }
]

CATEGORY_COLORS = {
    "student": 0x06b6d4,      # Cyan
    "desi_family": 0x8b5cf6,  # Purple
    "corporate": 0x10b981,    # Emerald
    "classics": 0xf59e0b,     # Amber
    "dating": 0xf43f5e,       # Rose
    "daily_life": 0x3b82f6,   # Blue
    "tech": 0x6366f1          # Indigo
}

CATEGORY_NAMES = {
    "student": "🎓 Student & College Life",
    "desi_family": "🏠 Desi Family & Parents",
    "corporate": "💼 Office & Corporate",
    "classics": "🎅 Santa Banta & Pappu",
    "dating": "❤️ Dating & Relationships",
    "daily_life": "🛵 Daily Desi Life",
    "tech": "💻 Tech & Programming"
}

def load_jokes():
    try:
        if os.path.exists(JOKES_FILE):
            with open(JOKES_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
                if isinstance(data, list) and len(data) > 0:
                    return data
    except Exception as e:
        print(f"Error loading jokes from {JOKES_FILE}: {e}")
    return DEFAULT_JOKES

def get_random_joke(category: str = "any", exclude_setup: str = None):
    all_jokes = load_jokes()
    if category and category != "any":
        filtered = [j for j in all_jokes if j.get("category") == category]
        pool = filtered if filtered else all_jokes
    else:
        pool = all_jokes

    if exclude_setup and len(pool) > 1:
        candidates = [j for j in pool if j.get("setup") != exclude_setup]
        if candidates:
            return random.choice(candidates)

    return random.choice(pool)

def build_joke_embed(joke: dict, user: discord.User = None):
    cat = joke.get("category", "daily_life")
    color = CATEGORY_COLORS.get(cat, 0x2dd4bf)
    title = joke.get("title", "😂 Friday's Desi Joke")
    setup = joke.get("setup", "")
    punchline = joke.get("punchline", "")
    cat_label = CATEGORY_NAMES.get(cat, cat.title())

    embed = discord.Embed(
        title=title,
        color=color,
        description=f"**{setup}**\n\n💬 *{punchline}*"
    )
    
    footer_text = f"Category: {cat_label}"
    if user:
        footer_text += f" • Shared with {user.display_name}"
    embed.set_footer(text=footer_text, icon_url="https://cdn.discordapp.com/emojis/100000000000000000.png" if False else None)
    return embed


class JokeView(discord.ui.View):
    def __init__(self, category: str = "any", author_id: int = None):
        super().__init__(timeout=180)
        self.category = category
        self.author_id = author_id

    @discord.ui.button(label="Next Joke 🔄", style=discord.ButtonStyle.primary, custom_id="next_joke_btn")
    async def next_joke(self, interaction: discord.Interaction, button: discord.ui.Button):
        # Allow anyone or the invoker to roll another joke
        current_setup = None
        if interaction.message and interaction.message.embeds:
            old_desc = interaction.message.embeds[0].description or ""
            current_setup = old_desc.split("\n\n")[0].strip("*")

        new_joke = get_random_joke(self.category, exclude_setup=current_setup)
        new_embed = build_joke_embed(new_joke, user=interaction.user)
        await interaction.response.edit_message(embed=new_embed, view=self)

    async def on_timeout(self):
        # Disable button after 3 minutes of inactivity
        for item in self.children:
            if isinstance(item, discord.ui.Button):
                item.disabled = True
        # Silently pass if message cannot be edited on timeout
        try:
            if hasattr(self, 'message') and self.message:
                await self.message.edit(view=self)
        except Exception:
            pass
