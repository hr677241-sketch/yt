import random
import re


# ============ INTRO PARAGRAPHS ============
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
    "🔥 This is something you DON'T want to miss! Watch till the end for the best part!\n\n",
    "⚡ Get ready for something incredible! This video is going to blow your mind!\n\n",
]

# ============ CALL TO ACTION ============
CTAS = [
    "\n\n👍 If you enjoyed this video, please LIKE and SUBSCRIBE for more!\n",
    "\n\n🔔 Hit the bell icon to never miss an update! New videos daily!\n",
    "\n\n💬 Drop a comment below and let us know your thoughts! We read every comment!\n",
    "\n\n📢 Share this video with someone who needs to see this! Help us reach more people!\n",
    "\n\n⭐ Don't forget to subscribe for more amazing content every week!\n",
    "\n\n🙏 Your support means everything! Like, Subscribe & Share!\n",
    "\n\n🚀 SMASH that like button if you found this helpful! Subscribe for daily content!\n",
    "\n\n💯 If this helped you, hit LIKE and SUBSCRIBE! Turn on notifications! 🔔\n",
]

# ============ OUTROS ============
OUTROS = [
    "\n\n━━━━━━━━━━━━━━━━━━━━\n📌 Follow us for more content!\n\nDisclaimer: This video is for educational & entertainment purposes only.\n",
    "\n\n━━━━━━━━━━━━━━━━━━━━\n🎯 More videos coming soon - Stay tuned!\n\nAll rights belong to respective owners.\n",
    "\n\n━━━━━━━━━━━━━━━━━━━━\n🌟 Thank you for watching! See you in the next one!\n\nFair use - educational content.\n",
    "\n\n━━━━━━━━━━━━━━━━━━━━\n✅ New videos every day! Subscribe now!\n\nContent used under fair use guidelines.\n",
    "\n\n━━━━━━━━━━━━━━━━━━━━\n🔥 Don't miss our other videos! Check the channel!\n\nFor educational purposes only.\n",
]

# ============ HASHTAG POOLS FOR DESCRIPTIONS ============
# These are DIFFERENT from title hashtags to maximize unique hashtag coverage
# YouTube allows max 15 unique hashtags (title + description combined)

DESC_HASHTAG_POOL_SHORT = [
    "#YouTubeShorts", "#ViralShorts", "#TrendingShorts", "#ShortsFeed",
    "#ShortsVideo", "#IndianCreators", "#ContentCreator", "#CreatorLife",
    "#Reels", "#ViralVideo", "#TrendingNow", "#Subscribe",
    "#NewVideo", "#ComedyShorts", "#LearnOnYouTube", "#ExploreShorts",
    "#ShortsTrending", "#ShortsViral", "#DailyShorts", "#BestShorts",
    "#TopShorts", "#FunnyShorts", "#EducationalShorts", "#ShortsIndia",
    "#EntertainmentShorts", "#LifeHacks", "#DidYouKnow", "#WatchThis",
    "#ShortsFun", "#YoutuberLife", "#GrowOnYouTube", "#ShortsChallenge",
]

DESC_HASHTAG_POOL_VIDEO = [
    "#ViralVideo", "#TrendingNow", "#MustWatchVideo", "#YouTubeVideo",
    "#ContentCreator", "#IndianCreators", "#CreatorLife", "#NewVideo",
    "#Subscribe", "#YouTubeChannel", "#FullVideo", "#BestVideo",
    "#Explore", "#WatchNow", "#VideoOfTheDay", "#DailyVideo",
    "#EducationalVideo", "#Entertainment", "#TopContent", "#LearnOnYouTube",
    "#YouTubeGrowth", "#ViralContent", "#TrendingVideo", "#MustSee",
    "#GrowOnYouTube", "#YouTuber", "#ContentIsKing", "#VideoCreator",
    "#AmazingVideo", "#LifeHacks", "#DidYouKnow", "#BestOf2024",
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
        if any(skip in line.lower() for skip in [
            'instagram.com/', 'twitter.com/', 'facebook.com/',
            'linkedin.com/', 't.me/', 'discord.gg/',
            'patreon.com/', 'buymeacoffee',
            '@', 'follow me', 'my social',
            'subscribe to my', 'my channel',
            'whatsapp', 'telegram group',
        ]):
            continue

        if re.search(r'[\w\.-]+@[\w\.-]+', line):
            continue

        if re.search(r'\+?\d{10,}', line):
            continue

        # Remove existing hashtags from original (we add our own)
        line = re.sub(r'#\w+', '', line).strip()

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
    lines = desc.split('\n')
    cleaned = []
    for line in lines:
        if re.match(r'^\s*\d{1,2}:\d{2}', line):
            if random.random() < 0.5:
                continue
        cleaned.append(line)
    return '\n'.join(cleaned)


def build_hashtag_block(is_short):
    """
    Build a large hashtag block for the description.
    Picks 10-12 random hashtags from the pool.
    These are DIFFERENT from title hashtags for maximum unique coverage.
    """
    if is_short:
        pool = DESC_HASHTAG_POOL_SHORT
    else:
        pool = DESC_HASHTAG_POOL_VIDEO

    # Pick 10-12 random hashtags
    count = random.randint(10, 12)
    selected = random.sample(pool, min(count, len(pool)))

    # Format as a nice block
    hashtag_block = "\n\n🏷️ TAGS:\n" + " ".join(selected)

    return hashtag_block


def build_seo_keywords(title, is_short):
    """Generate SEO keyword line from title for extra discoverability."""
    if not title:
        return ""

    # Extract meaningful words from title (skip short/common words)
    stop_words = {'the', 'a', 'an', 'is', 'it', 'in', 'on', 'at', 'to',
                  'for', 'of', 'and', 'or', 'but', 'not', 'with', 'this',
                  'that', 'from', 'by', 'as', 'are', 'was', 'be', 'has',
                  'had', 'do', 'does', 'did', 'will', 'can', 'could',
                  'would', 'should', 'may', 'might', 'shall', 'so', 'if',
                  'how', 'what', 'when', 'where', 'who', 'why', 'which'}

    # Remove hashtags and special chars from title
    clean_title = re.sub(r'#\w+', '', title)
    clean_title = re.sub(r'[^\w\s]', '', clean_title)
    words = [w.lower() for w in clean_title.split() if w.lower() not in stop_words and len(w) > 2]

    if not words:
        return ""

    # Build keyword phrases
    keywords = list(set(words))[:8]
    random.shuffle(keywords)

    return "\n\n🔍 Keywords: " + ", ".join(keywords)


def modify_description(original_desc, new_title="", is_short=False):
    """
    Main function: take original description → return unique description
    with full hashtag blocks for maximum reach.
    """
    if not original_desc or len(original_desc.strip()) < 10:
        return generate_fresh_description(new_title, is_short)

    desc = original_desc.strip()

    # Step 1: Clean (remove social links, emails, old hashtags)
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

    # Step 8: Add SEO keywords from title
    seo = build_seo_keywords(new_title, is_short)

    # Step 9: Add hashtag block (10-12 hashtags)
    hashtags = build_hashtag_block(is_short)

    # Build final description
    final = intro + desc + cta + outro + seo + hashtags

    # Clean up multiple blank lines
    final = re.sub(r'\n{4,}', '\n\n\n', final)

    return final[:5000]


def generate_fresh_description(title="", is_short=False):
    """Generate a completely new description if original is empty."""
    intro = random.choice(INTROS)
    cta = random.choice(CTAS)
    outro = random.choice(OUTROS)
    seo = build_seo_keywords(title, is_short)
    hashtags = build_hashtag_block(is_short)

    if title:
        # Clean title of hashtags for the description text
        clean_title = re.sub(r'#\w+', '', title).strip()
        middle = (
            f"📌 This video covers: {clean_title}\n\n"
            f"We hope you find this content helpful and informative.\n"
            f"If you enjoy this type of content, make sure to SUBSCRIBE "
            f"and turn on notifications so you never miss an upload!"
        )
    else:
        middle = (
            "We hope you find this content helpful and informative.\n"
            "If you enjoy this type of content, make sure to SUBSCRIBE "
            "and turn on notifications so you never miss an upload!"
        )

    return (intro + middle + cta + outro + seo + hashtags)[:5000]


def modify_tags(original_tags):
    """Modify and expand tags for maximum discoverability."""
    if not original_tags:
        original_tags = []

    new_tags = []

    for tag in original_tags[:12]:
        new_tags.append(tag)

        # Add variations
        if random.random() < 0.5:
            new_tags.append(tag + " 2024")
        if random.random() < 0.3:
            new_tags.append(tag + " tutorial")
        if random.random() < 0.3:
            new_tags.append("best " + tag)
        if random.random() < 0.2:
            new_tags.append(tag + " hindi")

    # Add viral/trending tags
    viral_tags = [
        "trending", "viral", "viral video", "must watch",
        "trending now", "latest", "new video", "top video",
        "how to", "tutorial", "guide", "tips and tricks",
        "2024", "new", "best", "top", "amazing",
        "shorts", "youtube shorts", "viral shorts",
        "indian creator", "content creator", "subscribe",
        "explore", "fyp", "for you", "trending today",
    ]
    random.shuffle(viral_tags)
    new_tags.extend(viral_tags[:10])

    # Remove duplicates, limit to 30
    seen = set()
    unique = []
    for t in new_tags:
        if t.lower() not in seen and len(t.strip()) > 0:
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

    print("=" * 60)
    print("ORIGINAL:")
    print(test_desc)
    print("\n" + "=" * 60)
    print("\nMODIFIED (VIDEO):")
    print(modify_description(test_desc, "🔥 How to Cook Pasta #Viral #Trending #MustWatch", is_short=False))
    print("\n" + "=" * 60)
    print("\nMODIFIED (SHORT):")
    print(modify_description(test_desc, "😱 Pasta Hack #Shorts #Viral #Trending", is_short=True))
    print("\n" + "=" * 60)
    print("\nFRESH DESCRIPTION:")
    print(generate_fresh_description("Amazing Cooking Tips", is_short=True))
    print("\n" + "=" * 60)
    print("\nMODIFIED TAGS:")
    print(modify_tags(["pasta", "cooking", "recipe", "food"]))
