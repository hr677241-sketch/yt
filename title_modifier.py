import random
import re


# ============ WORD REPLACEMENTS ============
SYNONYMS = {
    "how to": ["ways to", "learn to", "guide to", "steps to"],
    "best": ["top", "greatest", "ultimate", "amazing"],
    "top": ["best", "greatest", "ultimate"],
    "easy": ["simple", "quick", "effortless"],
    "simple": ["easy", "quick", "basic"],
    "fast": ["quick", "rapid", "speedy"],
    "quick": ["fast", "rapid", "speedy"],
    "make": ["create", "build", "prepare"],
    "create": ["make", "build", "design"],
    "learn": ["discover", "master", "understand"],
    "amazing": ["incredible", "awesome", "stunning"],
    "awesome": ["amazing", "incredible", "fantastic"],
    "beautiful": ["stunning", "gorgeous", "lovely"],
    "big": ["huge", "massive", "large"],
    "small": ["tiny", "little", "mini"],
    "good": ["great", "excellent", "wonderful"],
    "great": ["excellent", "wonderful", "fantastic"],
    "new": ["latest", "fresh", "brand new"],
    "old": ["classic", "vintage", "traditional"],
    "free": ["no cost", "complimentary", "zero cost"],
    "tips": ["tricks", "hacks", "advice"],
    "tricks": ["tips", "hacks", "techniques"],
    "tutorial": ["guide", "walkthrough", "lesson"],
    "guide": ["tutorial", "walkthrough", "handbook"],
    "review": ["overview", "breakdown", "analysis"],
    "complete": ["full", "total", "comprehensive"],
    "full": ["complete", "total", "entire"],
    "beginners": ["newbies", "starters", "newcomers"],
    "advanced": ["pro", "expert", "professional"],
    "secret": ["hidden", "unknown", "insider"],
    "powerful": ["strong", "effective", "potent"],
    "important": ["essential", "crucial", "vital"],
    "perfect": ["ideal", "flawless", "optimal"],
    "update": ["upgrade", "latest version", "new version"],
    "problem": ["issue", "challenge", "trouble"],
    "fix": ["solve", "repair", "resolve"],
    "way": ["method", "approach", "technique"],
    "use": ["utilize", "apply", "employ"],
    "get": ["obtain", "grab", "acquire"],
    "show": ["demonstrate", "reveal", "present"],
    "watch": ["see", "check out", "view"],
    "money": ["cash", "income", "earnings"],
    "work": ["function", "operate", "perform"],
    "start": ["begin", "launch", "kick off"],
    "stop": ["end", "halt", "cease"],
    "video": ["clip", "footage", "content"],
    "part": ["episode", "section", "segment"],
    "day": ["daily", "everyday", "24 hours"],
    "home": ["house", "at home", "indoor"],
    "world": ["globe", "planet", "worldwide"],
    "first": ["1st", "initial", "primary"],
    "last": ["final", "ultimate", "latest"],
    "real": ["actual", "genuine", "authentic"],
    "official": ["original", "authentic", "legitimate"],
    "vs": ["versus", "compared to", "against"],
    "and": ["&", "plus", "along with"],
    "with": ["featuring", "using", "w/"],
    "without": ["w/o", "minus", "excluding"],
    "in": ["inside", "within", "during"],
}

# Phrases to add at end of title
SUFFIXES = [
    " - Must Watch",
    " | Tips & Tricks",
    " (You Won't Believe)",
    " - Complete Guide",
    " | Step by Step",
    " - Easy Method",
    " | 2024",
    " | Hindi",
    " - Watch Now",
    " | Full Guide",
    " - Pro Tips",
    " | Explained",
    " (Working)",
    " | Latest",
    "",   # sometimes add nothing
    "",
    "",
]

# Phrases to add at start of title
PREFIXES = [
    "",   # most times add nothing at start
    "",
    "",
    "",
    "",
    "🔥 ",
    "✅ ",
    "⭐ ",
    "💡 ",
]


def replace_synonyms(title):
    """Replace some words with synonyms."""
    title_lower = title.lower()
    modified = title

    for word, replacements in SYNONYMS.items():
        # Check if word exists in title (case insensitive)
        pattern = re.compile(re.escape(word), re.IGNORECASE)
        if pattern.search(modified):
            # 60% chance to replace each found word
            if random.random() < 0.6:
                replacement = random.choice(replacements)

                # Match original case roughly
                match = pattern.search(modified)
                original = match.group()
                if original[0].isupper():
                    replacement = replacement.capitalize()

                modified = pattern.sub(replacement, modified, count=1)

    return modified


def rearrange_title(title):
    """Sometimes rearrange parts of the title."""
    separators = [" - ", " | ", " : ", " — "]

    for sep in separators:
        if sep in title:
            parts = title.split(sep)
            if len(parts) == 2 and random.random() < 0.5:
                # Swap the two parts
                return parts[1].strip() + sep + parts[0].strip()

    return title


def modify_title(original_title):
    """
    Main function: take original title → return modified unique title.
    Applies multiple changes to make it unique.
    """
    title = original_title.strip()

    # Remove any existing emojis at start (clean slate)
    title = re.sub(r'^[^\w\s]+\s*', '', title).strip()

    # Step 1: Replace synonyms
    title = replace_synonyms(title)

    # Step 2: Maybe rearrange
    if random.random() < 0.3:
        title = rearrange_title(title)

    # Step 3: Add prefix (emoji)
    prefix = random.choice(PREFIXES)
    title = prefix + title

    # Step 4: Add suffix
    suffix = random.choice(SUFFIXES)

    # Make sure total length stays under 100
    if len(title + suffix) <= 100:
        title = title + suffix

    # Step 5: Clean up
    title = title.strip()
    title = re.sub(r'\s+', ' ', title)  # Remove double spaces

    # Make sure it's different from original
    if title.lower() == original_title.lower():
        title = title + " | Guide"

    return title[:100]  # YouTube max title length


# ============ TEST ============
if __name__ == "__main__":
    test_titles = [
        "How to Cook Pasta at Home",
        "Top 10 Best Android Apps 2024",
        "Easy DIY Home Decoration Ideas",
        "Complete Python Tutorial for Beginners",
        "iPhone vs Samsung - Which is Better?",
        "5 Secret Tips to Make Money Online",
        "Full Review of New MacBook Pro",
    ]

    for t in test_titles:
        print(f"ORIGINAL: {t}")
        for i in range(3):
            print(f"  TRY {i+1}:  {modify_title(t)}")
        print()
