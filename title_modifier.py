import random
import re


# ============ WORD REPLACEMENTS ============
SYNONYMS = {
    "how to": ["ways to", "learn to", "guide to", "steps to", "secrets to"],
    "best": ["top", "greatest", "ultimate", "amazing", "insane"],
    "top": ["best", "greatest", "ultimate", "number 1"],
    "easy": ["simple", "quick", "effortless", "super easy"],
    "simple": ["easy", "quick", "basic", "beginner friendly"],
    "fast": ["quick", "rapid", "speedy", "lightning fast"],
    "quick": ["fast", "rapid", "speedy", "instant"],
    "make": ["create", "build", "prepare", "craft"],
    "create": ["make", "build", "design", "craft"],
    "learn": ["discover", "master", "understand", "unlock"],
    "amazing": ["incredible", "awesome", "stunning", "mind blowing"],
    "awesome": ["amazing", "incredible", "fantastic", "epic"],
    "beautiful": ["stunning", "gorgeous", "lovely", "breathtaking"],
    "big": ["huge", "massive", "large", "giant"],
    "small": ["tiny", "little", "mini", "compact"],
    "good": ["great", "excellent", "wonderful", "superb"],
    "great": ["excellent", "wonderful", "fantastic", "phenomenal"],
    "new": ["latest", "fresh", "brand new", "newest"],
    "old": ["classic", "vintage", "traditional", "retro"],
    "free": ["no cost", "complimentary", "zero cost", "100% free"],
    "tips": ["tricks", "hacks", "advice", "secrets"],
    "tricks": ["tips", "hacks", "techniques", "methods"],
    "tutorial": ["guide", "walkthrough", "lesson", "masterclass"],
    "guide": ["tutorial", "walkthrough", "handbook", "blueprint"],
    "review": ["overview", "breakdown", "analysis", "deep dive"],
    "complete": ["full", "total", "comprehensive", "detailed"],
    "full": ["complete", "total", "entire", "uncut"],
    "beginners": ["newbies", "starters", "newcomers", "first timers"],
    "advanced": ["pro", "expert", "professional", "elite"],
    "secret": ["hidden", "unknown", "insider", "unrevealed"],
    "powerful": ["strong", "effective", "potent", "game changing"],
    "important": ["essential", "crucial", "vital", "critical"],
    "perfect": ["ideal", "flawless", "optimal", "ultimate"],
    "update": ["upgrade", "latest version", "new version"],
    "problem": ["issue", "challenge", "trouble", "struggle"],
    "fix": ["solve", "repair", "resolve", "overcome"],
    "way": ["method", "approach", "technique", "strategy"],
    "use": ["utilize", "apply", "employ", "leverage"],
    "get": ["obtain", "grab", "acquire", "unlock"],
    "show": ["demonstrate", "reveal", "present", "expose"],
    "watch": ["see", "check out", "view", "witness"],
    "money": ["cash", "income", "earnings", "revenue"],
    "work": ["function", "operate", "perform", "deliver"],
    "start": ["begin", "launch", "kick off", "jumpstart"],
    "stop": ["end", "halt", "cease", "quit"],
    "video": ["clip", "footage", "content"],
    "part": ["episode", "section", "segment", "chapter"],
    "day": ["daily", "everyday", "24 hours"],
    "home": ["house", "at home", "indoor"],
    "world": ["globe", "planet", "worldwide"],
    "first": ["1st", "initial", "primary"],
    "last": ["final", "ultimate", "latest"],
    "real": ["actual", "genuine", "authentic", "legit"],
    "official": ["original", "authentic", "legitimate"],
    "vs": ["versus", "compared to", "against"],
    "and": ["&", "plus", "along with"],
    "with": ["featuring", "using", "w/"],
    "without": ["w/o", "minus", "excluding"],
    "try": ["attempt", "test", "experiment"],
    "never": ["don't ever", "absolutely not", "zero chance"],
    "always": ["every time", "consistently", "without fail"],
    "change": ["transform", "revolutionize", "upgrade"],
    "help": ["assist", "support", "aid"],
    "need": ["require", "must have", "essential"],
    "want": ["desire", "crave", "wish for"],
    "think": ["believe", "consider", "imagine"],
    "know": ["realize", "understand", "discover"],
    "life": ["lifestyle", "living", "everyday life"],
}

# ============ HASHTAG COMBOS FOR SHORTS TITLES ============
TITLE_TAGS_SHORT = [
    "#Shorts #Viral #Trending",
    "#Shorts #FYP #Viral #Trending",
    "#Shorts #GoViral #Trending",
    "#Shorts #Viral #MustWatch",
    "#Shorts #Trending #FYP",
    "#Shorts #ViralShorts #Trending",
    "#Shorts #Viral #Explore",
    "#Shorts #FYP #MustWatch",
    "#Shorts #TrendingNow #Viral",
    "#Shorts #Viral #OMG",
    "#Shorts #GoViral #FYP",
    "#Shorts #Viral #WatchThis",
    "#Shorts #ForYou #Viral",
    "#Shorts #Trending #OMG",
    "#Shorts #Viral #Trending #FYP",
    "#Shorts #ViralShorts #FYP",
    "#Shorts #Trending #ForYou",
    "#Shorts #Viral #MindBlown",
    "#Shorts #FYP #Explore #Viral",
    "#Shorts #GoViral #MustWatch",
]

# ============ HASHTAG COMBOS FOR VIDEO TITLES ============
TITLE_TAGS_VIDEO = [
    "#Viral #Trending #MustWatch",
    "#Trending #Viral #YouTube",
    "#MustWatch #Viral #Trending",
    "#Viral #Explore #Trending",
    "#YouTube #Viral #Trending",
    "#Trending #MustWatch #Viral",
    "#Viral #WatchNow #Trending",
    "#TopVideo #Viral #Trending",
    "#Viral #Trending #2024",
    "#BestOf #Viral #Trending",
    "#MustSee #Viral #Trending",
    "#Viral #Trending #WatchThis",
    "#GoViral #Trending #YouTube",
    "#Viral #FullVideo #Trending",
    "#Trending #Viral #MustSee",
    "#Viral #Trending #Explore",
    "#MustWatch #YouTube #Viral",
    "#Viral #Trending #MindBlown",
    "#WatchNow #Viral #Trending",
    "#Viral #Trending #OMG",
]

# ============ PREFIXES (emojis for CTR) ============
PREFIXES = [
    "🔥 ", "✅ ", "⭐ ", "💡 ", "😱 ", "🚀 ", "💥 ", "⚡ ",
    "🎯 ", "👀 ", "❤️ ", "💯 ", "🏆 ", "📢 ", "🎬 ", "😍 ",
    "🤯 ", "👑 ", "⚠️ ", "🔴 ",
    "",  # sometimes no emoji
    "",
    "",
]

# ============ ENGAGEMENT SUFFIXES ============
SUFFIXES = [
    " - Must Watch!",
    " | Watch Till End!",
    " - You Won't Believe!",
    " | Mind Blowing!",
    " - Don't Miss!",
    " | Wait For It!",
    " - OMG!",
    " | Unbelievable!",
    " - Shocking!",
    " | Game Changer!",
    " - Try This!",
    " | So Satisfying!",
    "",  # sometimes no suffix
    "",
    "",
    "",
]


def replace_synonyms(title):
    """Replace some words with synonyms."""
    modified = title

    for word, replacements in SYNONYMS.items():
        pattern = re.compile(re.escape(word), re.IGNORECASE)
        if pattern.search(modified):
            if random.random() < 0.6:
                replacement = random.choice(replacements)
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
                return parts[1].strip() + sep + parts[0].strip()

    return title


def modify_title(original_title, is_short=False):
    """
    Main function: take original title → return modified unique title
    with multiple hashtags for maximum reach.
    """
    title = original_title.strip()

    # Remove existing emojis at start
    title = re.sub(r'^[^\w\s]+\s*', '', title).strip()

    # Remove any existing hashtags from original
    title = re.sub(r'#\w+', '', title).strip()
    title = re.sub(r'\s+', ' ', title).strip()

    if not title:
        title = "Amazing Video"

    # Step 1: Replace synonyms
    title = replace_synonyms(title)

    # Step 2: Maybe rearrange
    if random.random() < 0.3:
        title = rearrange_title(title)

    # Step 3: Add prefix (emoji)
    prefix = random.choice(PREFIXES)
    title = prefix + title

    # Step 4: Select hashtag combo
    if is_short:
        hashtags = random.choice(TITLE_TAGS_SHORT)
    else:
        hashtags = random.choice(TITLE_TAGS_VIDEO)

    # Step 5: Select suffix
    suffix = random.choice(SUFFIXES)

    # Step 6: Build final title — HASHTAGS ARE PRIORITY
    # Reserve space for hashtags first, then fit title + suffix
    hashtag_len = len(hashtags) + 1  # +1 for space before hashtags
    max_title_len = 100 - hashtag_len

    # Try title + suffix
    title_with_suffix = title + suffix
    if len(title_with_suffix) <= max_title_len:
        title_text = title_with_suffix
    elif len(title) <= max_title_len:
        title_text = title
    else:
        # Truncate title to fit hashtags
        title_text = title[:max_title_len - 3].strip() + "..."

    final = f"{title_text} {hashtags}"

    # Clean up
    final = final.strip()
    final = re.sub(r'\s+', ' ', final)

    # Make sure it's different from original
    clean_final = re.sub(r'#\w+', '', final).strip().lower()
    clean_orig = original_title.strip().lower()
    if clean_final == clean_orig:
        final = f"🔥 {title_text} {hashtags}"

    return final[:100]


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
        print(f"  SHORT:  {modify_title(t, is_short=True)}")
        print(f"  VIDEO:  {modify_title(t, is_short=False)}")
        print()
