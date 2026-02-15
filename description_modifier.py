import random
import re


# ============ INTRO PARAGRAPHS (added at top) ============
INTROS = [
    "In this video, we're going to explore something really interesting. Make sure you watch till the end!\n\n",
    "Hey everyone! Welcome back to the channel. Today we have something special for you.\n\n",
    "What's up guys! In today's video, we're diving deep into this topic. Let's get started!\n\n",
    "Welcome to another exciting video! Don't forget to like and subscribe if you find this helpful.\n\n",
    "Hey there! If you're looking for the best content on this topic, you're in the right place.\n\n",
    "Thanks for watching! This is one of our most requested topics. Let's jump right in!\n\n",
    "In this detailed video, we cover everything you need to know. Stay tuned!\n\n",
    "Hello friends! Today's video is packed with value. Make sure to watch it completely.\n\n",
    "Welcome! This video will change the way you think about this topic. Let's begin!\n\n",
    "What's going on everyone! You asked for it, and here it is. Let's dive in!\n\n",
]

# ============ CALL TO ACTION (added in middle) ============
CTAS = [
    "\n\n👍 If you enjoyed this video, please LIKE and SUBSCRIBE!\n",
    "\n\n🔔 Hit the bell icon to never miss an update!\n",
    "\n\n💬 Drop a comment below and let us know your thoughts!\n",
    "\n\n📢 Share this video with someone who needs to see this!\n",
    "\n\n⭐ Don't forget to subscribe for more amazing content!\n",
    "\n\n🙏 Your support means everything! Like & Subscribe!\n",
]

# ============ OUTROS (added at end) ============
OUTROS = [
    "\n\n━━━━━━━━━━━━━━━━━━━━\n📌 Follow us for more content!\n\nDisclaimer: This video is for educational purposes only.\n",
    "\n\n━━━━━━━━━━━━━━━━━━━━\n🎯 More videos coming soon - Stay tuned!\n\nAll rights belong to respective owners.\n",
    "\n\n━━━━━━━━━━━━━━━━━━━━\n🌟 Thank you for watching!\n\nFair use - educational content.\n",
    "\n\n━━━━━━━━━━━━━━━━━━━━\n✅ New videos every week!\n\nContent used under fair use.\n",
]

# ============ ASIA HASHTAGS (FIXED BLOCK) ============
ASIA_HASHTAGS = [
    "#Shorts",
    "#YouTubeShorts",
    "#ViralShorts",
    "#TrendingShorts",
    "#IndianCreators",
    "#CreatorLife",
    "#ContentCreators",
    "#ComedyShorts",
    "#LearnOnYouTube",
    "#ExploreShorts"
]

# ============ WORD REPLACEMENTS FOR DESCRIPTIONS ============
DESC_REPLACEMENTS = {
    "in this video": "in today's video",
    "hi guys": "hey everyone",
    "hey guys": "hello friends",
    "hello everyone": "hey there",
    "subscribe": "hit subscribe",
    "like button": "thumbs up button",
    "comment below": "share your thoughts below",
    "check out": "take a look at",
    "don't forget": "make sure",
    "please": "kindly",
    "awesome": "amazing",
    "amazing": "incredible",
    "great": "fantastic",
    "good": "excellent",
    "best": "top-rated",
    "watch": "check out",
    "click": "tap",
    "link": "URL",
    "follow me": "follow us",
    "my channel": "our channel",
    "i will": "we will",
    "i am": "we are",
    "i have": "we have",
}


def clean_description(desc):
    """Remove problematic elements from original description."""
    lines = desc.split('\n')
    cleaned = []

    for line in lines:
        # Skip lines with original channel links
        if any(skip in line.lower() for skip in [
            'instagram.com/', 'twitter.com/', 'facebook.com/',
            'linkedin.com/', 't.me/', 'discord.gg/',
            'patreon.com/', 'buymeacoffee',
            '@', 'follow me', 'my social',
            'subscribe to my', 'my channel',
            'whatsapp', 'telegram group',
        ]):
            continue

        # Skip email addresses
        if re.search(r'[\w\.-]+@[\w\.-]+', line):
            continue

        # Skip phone numbers
        if re.search(r'\+?\d{10,}', line):
            continue

        cleaned.append(line)

    return '\n'.join(cleaned)


def replace_words_in_desc(desc):
    """Replace common phrases with alternatives."""
    modified = desc

    for original, replacement in DESC_REPLACEMENTS.items():
        pattern = re.compile(re.escape(original), re.IGNORECASE)
        if pattern.search(modified) and random.random() < 0.5:
            modified = pattern.sub(replacement, modified, count=1)

    return modified


def remove_timestamps(desc):
    """Remove or modify timestamps."""
    # Remove lines like "0:00 - Intro" or "02:30 Chapter 2"
    lines = desc.split('\n')
    cleaned = []
    for line in lines:
        if re.match(r'^\s*\d{1,2}:\d{2}', line):
            # 50% chance to remove timestamps
            if random.random() < 0.5:
                continue
        cleaned.append(line)
    return '\n'.join(cleaned)


def build_hashtag_block(is_short):
    """Return the hashtag block as a string."""
    if is_short:
        # Ensure #Shorts is first, then the rest (avoid duplicate)
        hashtags = list(ASIA_HASHTAGS)
        if "#Shorts" in hashtags:
            hashtags.remove("#Shorts")
        hashtags.insert(0, "#Shorts")
        return "\n\n" + " ".join(hashtags)
    else:
        # For regular videos, use the full set
        return "\n\n" + " ".join(ASIA_HASHTAGS)


def modify_description(original_desc, new_title="", is_short=False):
    """
    Main function: take original description → return unique description.
    Now accepts is_short flag to build the correct hashtag block.
    """
    if not original_desc or len(original_desc.strip()) < 10:
        # If no description, generate one
        return generate_fresh_description(new_title, is_short)

    desc = original_desc.strip()

    # Step 1: Clean (remove social links, emails etc)
    desc = clean_description(desc)

    # Step 2: Remove/modify timestamps
    desc = remove_timestamps(desc)

    # Step 3: Replace words
    desc = replace_words_in_desc(desc)

    # Step 4: Trim to first 800 chars of original
    if len(desc) > 800:
        desc = desc[:800] + "..."

    # Step 5: Add new intro at top
    intro = random.choice(INTROS)

    # Step 6: Add call to action
    cta = random.choice(CTAS)

    # Step 7: Add outro
    outro = random.choice(OUTROS)

    # Step 8: Add fixed Asia hashtags (instead of random HASHTAG_SETS)
    hashtags = build_hashtag_block(is_short)

    # Build final description
    final = intro + desc + cta + outro + hashtags

    # Clean up multiple blank lines
    final = re.sub(r'\n{4,}', '\n\n\n', final)

    return final[:5000]  # YouTube max description length


def generate_fresh_description(title="", is_short=False):
    """Generate a completely new description if original is empty."""
    intro = random.choice(INTROS)
    cta = random.choice(CTAS)
    outro = random.choice(OUTROS)
    hashtags = build_hashtag_block(is_short)

    middle = f"This video covers: {title}\n\nWe hope you find this content helpful and informative." if title else ""

    return (intro + middle + cta + outro + hashtags)[:5000]


def modify_tags(original_tags):
    """Modify and expand tags."""
    if not original_tags:
        original_tags = []

    new_tags = []

    for tag in original_tags[:15]:
        new_tags.append(tag)

        # Add variations
        if random.random() < 0.5:
            new_tags.append(tag + " 2024")
        if random.random() < 0.3:
            new_tags.append(tag + " tutorial")
        if random.random() < 0.3:
            new_tags.append("best " + tag)

    # Add generic trending tags
    extra = [
        "trending", "viral", "must watch", "latest",
        "how to", "tutorial", "guide", "tips",
        "2024", "new", "best", "top",
    ]
    random.shuffle(extra)
    new_tags.extend(extra[:5])

    # Remove duplicates, limit to 30
    seen = set()
    unique = []
    for t in new_tags:
        if t.lower() not in seen:
            seen.add(t.lower())
            unique.append(t)

    return unique[:30]


# ============ TEST ============
if __name__ == "__main__":
    test_desc = """In this video I show you how to cook pasta at home.
It's really easy and anyone can do it!

0:00 - Intro
1:30 - Ingredients
3:00 - Cooking
5:00 - Final Result

Follow me on Instagram: @chef_example
Email: chef@example.com

Don't forget to subscribe and hit the like button!
Check out my other videos for more recipes."""

    print("ORIGINAL:")
    print(test_desc)
    print("\n" + "=" * 60)
    print("\nMODIFIED (standard video):")
    print(modify_description(test_desc, "How to Cook Pasta", is_short=False))
    print("\n" + "=" * 60)
    print("\nMODIFIED (Shorts):")
    print(modify_description(test_desc, "How to Cook Pasta", is_short=True))
    print("\n" + "=" * 60)
    print("\nMODIFIED TAGS:")
    print(modify_tags(["pasta", "cooking", "recipe", "food"]))
