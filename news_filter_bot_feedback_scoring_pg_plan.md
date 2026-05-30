# Developer Task: Rebuild Telegram News Filter Bot with Scoring, Feedback, and PostgreSQL

## 1. Context

We already have a Telegram bot that filters Telegram channel posts using:

- stop words;
- contextual filtering;
- removal of memes, jokes, low-value entertainment posts, and noisy content.

We need to change the product logic.

The bot should no longer generate scheduled digests.

Instead, it should work as a near-real-time personalized news monitor:

1. Every 5 minutes it checks selected Telegram channels for new posts.
2. For each new post it generates a structured set of features.
3. It calculates a personalized score.
4. If the score is high enough, it sends the post to the user immediately.
5. The message must include the source link.
6. Under each sent post there must be 4 inline feedback buttons in one row:
   - 👍 Больше такого
   - 👎 Меньше такого
   - ⭐ Очень важно
   - 🗑 Скрывать такое
7. User feedback must update the user's preference profile and affect future scoring.

At the moment there is no PostgreSQL. We need to add PostgreSQL and persist all important data.

For now, do not implement embeddings or vector search.

---

## 2. New Product Behavior

Expected flow:

```text
Telegram channels
    ↓
Post monitor runs every 5 minutes
    ↓
New posts are collected
    ↓
Hard filters remove obvious noise
    ↓
LLM extracts structured features
    ↓
Scoring engine calculates personalized score
    ↓
If score >= threshold, send post to user
    ↓
User presses feedback button
    ↓
Preference profile is updated
    ↓
Future scoring changes
```

Important: do not train a custom ML model at this stage.

Use:

```text
LLM feature extraction
+ deterministic scoring
+ user feedback buttons
+ PostgreSQL preference storage
```

The system should be simple, transparent, debuggable, and adjustable.

---

## 3. Required Tech Changes

### 3.1 Add PostgreSQL

Add PostgreSQL to the project.

If the app is Docker-based, add a `postgres` service to `docker-compose.yml`.

Example:

```yaml
services:
  postgres:
    image: postgres:16-alpine
    container_name: news-filter-postgres
    restart: unless-stopped
    environment:
      POSTGRES_DB: news_filter_bot
      POSTGRES_USER: news_filter_user
      POSTGRES_PASSWORD: ${POSTGRES_PASSWORD}
    volumes:
      - postgres_data:/var/lib/postgresql/data
    ports:
      - "5432:5432"

volumes:
  postgres_data:
```

The app must read the database connection from:

```env
DATABASE_URL=postgresql://news_filter_user:${POSTGRES_PASSWORD}@postgres:5432/news_filter_bot
```

---

## 4. Environment Variables

Add or update environment variables:

```env
BOT_TOKEN=
OWNER_TELEGRAM_ID=

TELEGRAM_API_ID=
TELEGRAM_API_HASH=
TELEGRAM_USER_SESSION=

DATABASE_URL=
POSTGRES_PASSWORD=

LLM_PROVIDER=deepseek
DEEPSEEK_API_KEY=
DEEPSEEK_MODEL=deepseek-chat

MONITOR_INTERVAL_MINUTES=5
DEFAULT_SCORE_THRESHOLD=70
TIMEZONE=Europe/Moscow
```

Optional:

```env
MAX_POSTS_PER_CHANNEL_PER_RUN=20
MIN_POST_LENGTH=80
ENABLE_DEBUG_SCORING=true
```

---

## 5. Database Schema

Use migrations. Do not create tables manually in application code.

### 5.1 users

```sql
CREATE TABLE users (
    id BIGSERIAL PRIMARY KEY,
    telegram_id BIGINT NOT NULL UNIQUE,
    username TEXT,
    first_name TEXT,
    timezone TEXT NOT NULL DEFAULT 'Europe/Moscow',
    score_threshold INTEGER NOT NULL DEFAULT 70,
    is_active BOOLEAN NOT NULL DEFAULT TRUE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
```

### 5.2 channels

Stores tracked Telegram channels.

The channel address is important because some channels are generally better, and this alone can increase or decrease the score.

```sql
CREATE TABLE channels (
    id BIGSERIAL PRIMARY KEY,
    user_id BIGINT NOT NULL REFERENCES users(id) ON DELETE CASCADE,

    channel_username TEXT,
    channel_title TEXT,
    channel_link TEXT,
    channel_address TEXT NOT NULL,

    channel_quality_weight INTEGER NOT NULL DEFAULT 0,
    is_active BOOLEAN NOT NULL DEFAULT TRUE,

    last_seen_message_id BIGINT,
    last_checked_at TIMESTAMPTZ,

    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    UNIQUE(user_id, channel_address)
);
```

Notes:

- `channel_address` should store a normalized channel identifier: for example `@channelname` or `https://t.me/channelname`.
- `channel_quality_weight` is a channel-level score modifier.
- Good channels can gradually receive positive weight.
- Low-quality channels can gradually receive negative weight.

### 5.3 posts

```sql
CREATE TABLE posts (
    id BIGSERIAL PRIMARY KEY,

    channel_id BIGINT NOT NULL REFERENCES channels(id) ON DELETE CASCADE,

    telegram_message_id BIGINT NOT NULL,
    source_url TEXT,

    text TEXT NOT NULL,
    text_hash TEXT NOT NULL,

    published_at TIMESTAMPTZ,
    collected_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    processing_status TEXT NOT NULL DEFAULT 'new',
    -- possible values:
    -- new
    -- skipped_hard_filter
    -- feature_extracted
    -- scored
    -- sent
    -- failed

    skip_reason TEXT,

    features_json JSONB,
    score_details_json JSONB,

    final_score INTEGER,
    sent_at TIMESTAMPTZ,

    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    UNIQUE(channel_id, telegram_message_id)
);
```

Recommended indexes:

```sql
CREATE INDEX idx_posts_status ON posts(processing_status);
CREATE INDEX idx_posts_channel_published ON posts(channel_id, published_at DESC);
CREATE INDEX idx_posts_final_score ON posts(final_score);
CREATE INDEX idx_posts_text_hash ON posts(text_hash);
```

### 5.4 user_feedback

Stores explicit user feedback from inline buttons.

```sql
CREATE TABLE user_feedback (
    id BIGSERIAL PRIMARY KEY,

    user_id BIGINT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    post_id BIGINT NOT NULL REFERENCES posts(id) ON DELETE CASCADE,

    feedback_type TEXT NOT NULL,
    -- possible values:
    -- more_like_this
    -- less_like_this
    -- very_important
    -- hide_similar

    weight INTEGER NOT NULL,

    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    UNIQUE(user_id, post_id)
);
```

Feedback weights:

```text
more_like_this  = +1
less_like_this  = -1
very_important  = +3
hide_similar    = -3
```

If the user changes feedback on the same post, update the existing row instead of creating duplicates.

### 5.5 user_preferences

Stores learned preferences based on feedback.

```sql
CREATE TABLE user_preferences (
    id BIGSERIAL PRIMARY KEY,

    user_id BIGINT NOT NULL REFERENCES users(id) ON DELETE CASCADE,

    feature_type TEXT NOT NULL,
    -- examples:
    -- topic
    -- entity
    -- content_type
    -- tone
    -- channel_address
    -- language

    feature_value TEXT NOT NULL,

    weight INTEGER NOT NULL DEFAULT 0,

    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    UNIQUE(user_id, feature_type, feature_value)
);
```

Recommended index:

```sql
CREATE INDEX idx_user_preferences_lookup
ON user_preferences(user_id, feature_type, feature_value);
```

### 5.6 processing_logs

Optional but recommended.

```sql
CREATE TABLE processing_logs (
    id BIGSERIAL PRIMARY KEY,

    post_id BIGINT REFERENCES posts(id) ON DELETE SET NULL,
    level TEXT NOT NULL,
    event TEXT NOT NULL,
    details_json JSONB,

    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
```

Use this for debugging failed LLM calls, skipped posts, score calculations, and delivery errors.

---

## 6. Feature Extraction

For every post that passes hard filters, call the LLM and ask it to return structured JSON.

The feature set must include the channel address.

The backend may inject `channel_address` into the features before scoring, even if the LLM does not return it.

Required features:

```json
{
  "topics": [],
  "entities": [],
  "content_type": "",
  "tone": "",
  "language": "",
  "channel_address": "",
  "is_ad": false,
  "is_meme_or_joke": false,
  "is_repost_without_value": false,
  "practical_value": 0,
  "business_value": 0,
  "technical_depth": 0,
  "novelty": 0,
  "urgency": 0,
  "noise_level": 0,
  "summary": "",
  "reasoning": ""
}
```

Scales:

```text
practical_value: 0-10
business_value: 0-10
technical_depth: 0-10
novelty: 0-10
urgency: 0-10
noise_level: 0-10
```

Recommended `content_type` values:

```text
news
analysis
tutorial
tool_release
case_study
opinion
announcement
job_post
advertisement
meme
personal_story
low_value_chat
other
```

Recommended `tone` values:

```text
serious
neutral
marketing
hype
humor
aggressive
low_quality
```

---

## 7. LLM Prompt for Feature Extraction

Use this prompt template:

```text
You are a strict Telegram post feature extraction engine.

Your task is to analyze a Telegram post and return structured JSON only.

The bot is used to filter useful professional/news content from Telegram channels.
The user does not want memes, low-value jokes, empty hype, generic motivational posts, obvious ads, or useless reposts.

Return JSON only. Do not add Markdown. Do not add explanations outside JSON.

Analyze the post using the following schema:

{
  "topics": ["short topic 1", "short topic 2"],
  "entities": ["company/tool/person/product names"],
  "content_type": "news | analysis | tutorial | tool_release | case_study | opinion | announcement | job_post | advertisement | meme | personal_story | low_value_chat | other",
  "tone": "serious | neutral | marketing | hype | humor | aggressive | low_quality",
  "language": "ru | en | uz | other",
  "is_ad": true/false,
  "is_meme_or_joke": true/false,
  "is_repost_without_value": true/false,
  "practical_value": 0-10,
  "business_value": 0-10,
  "technical_depth": 0-10,
  "novelty": 0-10,
  "urgency": 0-10,
  "noise_level": 0-10,
  "summary": "one or two concise sentences in Russian",
  "reasoning": "short explanation in Russian why the post is useful or useless"
}

Important rules:
- If the post is mostly a joke, meme, ironic comment, or low-value entertainment, set is_meme_or_joke=true and noise_level high.
- If the post is an ad, set is_ad=true.
- If the post contains practical steps, implementation details, useful tools, or business insights, increase practical_value and business_value.
- If the post contains technical details, increase technical_depth.
- If the post is just generic hype, reduce practical_value and increase noise_level.
- Keep topics short and reusable.
- Extract important entities such as tools, frameworks, companies, people, APIs, products, and platforms.
- Do not invent facts.
- Return valid JSON only.

Post source channel:
{{channel_address}}

Post text:
{{post_text}}
```

---

## 8. Hard Filters

Keep existing filters and add these checks before the LLM call.

A post should be skipped before LLM if:

- text is empty;
- text length is below `MIN_POST_LENGTH`;
- text hash already exists;
- it contains hard stop words;
- it is only a link;
- it contains only emoji;
- it is clearly a giveaway/contest;
- it is a service post with no useful content.

When a post is skipped, save it to `posts` with:

```text
processing_status = skipped_hard_filter
skip_reason = concrete reason
```

---

## 9. Scoring Engine

Do not rely on the LLM to decide whether to send the post.

The LLM extracts features only.

The backend calculates the score deterministically.

Base formula:

```text
score =
  40
  + topic_score
  + entity_score
  + content_type_score
  + tone_score
  + channel_score
  + value_score
  + urgency_score
  - noise_penalty
  - ad_penalty
  - meme_penalty
  - repost_penalty
```

Then clamp:

```text
score = max(0, min(100, score))
```

### 9.1 topic_score

For each topic in `features_json.topics`, look up:

```text
user_preferences.feature_type = 'topic'
user_preferences.feature_value = topic
```

Sum the weights.

```text
topic_score = clamp(sum_topic_weights, -20, +20)
```

### 9.2 entity_score

For each entity in `features_json.entities`, look up:

```text
feature_type = 'entity'
```

```text
entity_score = clamp(sum_entity_weights, -15, +15)
```

### 9.3 content_type_score

Look up:

```text
feature_type = 'content_type'
feature_value = features_json.content_type
```

Default scores:

```text
tutorial        +10
tool_release     +9
case_study       +8
analysis         +7
news             +4
announcement     +2
opinion           0
personal_story   -5
job_post         -8
advertisement   -25
meme            -30
low_value_chat  -30
other             0
```

Final:

```text
content_type_score = default_content_type_score + learned_content_type_weight
content_type_score = clamp(content_type_score, -30, +20)
```

### 9.4 tone_score

Defaults:

```text
serious       +5
neutral       +2
marketing     -8
hype         -10
humor        -12
aggressive    -8
low_quality  -20
```

Also add learned user preference for:

```text
feature_type = 'tone'
```

```text
tone_score = clamp(default_tone_score + learned_tone_weight, -20, +10)
```

### 9.5 channel_score

This is important.

Some Telegram channels are generally better than others, so the channel itself must affect scoring.

Use both:

1. `channels.channel_quality_weight`
2. learned user preference:

```text
feature_type = 'channel_address'
feature_value = channel_address
```

Formula:

```text
channel_score = channels.channel_quality_weight + learned_channel_weight
channel_score = clamp(channel_score, -25, +25)
```

This means that good channels can push posts above the threshold even if the post is only moderately useful.

Bad channels can lower the score even if the post looks okay.

### 9.6 value_score

Use numeric features from the LLM:

```text
value_score =
  practical_value * 1.5
  + business_value * 1.2
  + technical_depth * 1.0
  + novelty * 0.8

value_score = clamp(value_score, 0, +35)
```

### 9.7 urgency_score

```text
urgency_score = urgency * 0.8
urgency_score = clamp(urgency_score, 0, +8)
```

### 9.8 penalties

```text
noise_penalty = noise_level * 2
ad_penalty = is_ad ? 30 : 0
meme_penalty = is_meme_or_joke ? 35 : 0
repost_penalty = is_repost_without_value ? 20 : 0
```

### 9.9 score_details_json

Store all score components in `score_details_json`.

Example:

```json
{
  "base": 40,
  "topic_score": 8,
  "entity_score": 4,
  "content_type_score": 10,
  "tone_score": 5,
  "channel_score": 7,
  "value_score": 24,
  "urgency_score": 3,
  "noise_penalty": 2,
  "ad_penalty": 0,
  "meme_penalty": 0,
  "repost_penalty": 0,
  "final_score": 99
}
```

This is mandatory for debugging.

---

## 10. Sending Logic

If:

```text
final_score >= users.score_threshold
```

send the post to the user.

Default threshold:

```text
70
```

Message format:

```markdown
🔥 *Полезная новость*

*Источник:* @channel_address
*Оценка:* 84/100

*Краткое резюме:*
...

*Почему показал:*
...

[Открыть источник](https://t.me/...)
```

The source link is required.

Use the original Telegram post URL when possible.

---

## 11. Inline Feedback Buttons

Every sent post must have 4 inline buttons in one row:

```text
👍 Больше такого | 👎 Меньше такого | ⭐ Очень важно | 🗑 Скрывать такое
```

Callback data examples:

```text
fb:more_like_this:{post_id}
fb:less_like_this:{post_id}
fb:very_important:{post_id}
fb:hide_similar:{post_id}
```

If callback data becomes too long, use compact callback data:

```text
f:m:{post_id}
f:l:{post_id}
f:v:{post_id}
f:h:{post_id}
```

---

## 12. Feedback Processing

When the user clicks a button:

1. Parse callback data.
2. Verify user access.
3. Find the post.
4. Insert or update `user_feedback`.
5. Update `user_preferences`.
6. Optionally update `channels.channel_quality_weight`.
7. Send callback confirmation.

Confirmation examples:

```text
Учту: буду чаще показывать похожее.
Учту: буду реже показывать похожее.
Отмечено как очень важное.
Учту: похожее буду скрывать.
```

Feedback weights:

```text
more_like_this  = +1
less_like_this  = -1
very_important  = +3
hide_similar    = -3
```

---

## 13. Updating user_preferences

After feedback, update preferences based on the post's extracted features.

### Topics

```text
feature_type = topic
feature_value = each topic
delta = feedback_weight
```

### Entities

```text
feature_type = entity
feature_value = each entity
delta = feedback_weight
```

### Content type

```text
feature_type = content_type
feature_value = content_type
delta = feedback_weight
```

### Tone

```text
feature_type = tone
feature_value = tone
delta = feedback_weight
```

### Channel address

```text
feature_type = channel_address
feature_value = channel_address
delta = feedback_weight
```

Because channel quality is important, also update the channel preference.

Suggested channel preference deltas:

```text
more_like_this: +1 to channel_address
less_like_this: -1 to channel_address
very_important: +2 to channel_address
hide_similar: -2 to channel_address
```

---

## 14. Weight Limits

Clamp all preference weights:

```text
minimum weight = -30
maximum weight = +30
```

Pseudo-code:

```python
def update_preference(old_weight: int, delta: int) -> int:
    return max(-30, min(30, old_weight + delta))
```

---

## 15. Channel Quality Weight

In addition to `user_preferences`, the `channels` table has:

```text
channel_quality_weight
```

Update it slowly based on user feedback.

Suggested update:

```text
more_like_this: 0
less_like_this: 0
very_important: +1
hide_similar: -1
```

Clamp:

```text
channel_quality_weight = clamp(channel_quality_weight, -15, +15)
```

Reason:

- `user_preferences.channel_address` reacts faster.
- `channels.channel_quality_weight` should be slower and more stable.

---

## 16. Optional Weekly Decay

Recommended later, not required for MVP.

Once per week, slowly reduce old preference weights:

```text
weight = round(weight * 0.95)
```

This prevents the bot from being permanently biased by old feedback.

---

## 17. Monitoring Worker

Implement a worker that runs every 5 minutes.

It should:

1. Load active users.
2. Load active channels for each user.
3. For each channel, fetch posts newer than `last_seen_message_id` or newer than `last_checked_at`.
4. Store new posts in PostgreSQL.
5. Run hard filters.
6. Extract features via LLM.
7. Calculate score.
8. Save score and score details.
9. Send post if score is above threshold.
10. Update `last_seen_message_id` and `last_checked_at`.

Important:

- Avoid sending old channel history on first run.
- On first channel registration, save the latest message ID as `last_seen_message_id`, unless the user explicitly requests importing history.

---

## 18. Duplicate Handling

Avoid duplicate posts.

Use:

```text
UNIQUE(channel_id, telegram_message_id)
```

Also calculate `text_hash`.

If the same text appears in multiple channels, do not necessarily skip it globally at MVP stage, but store `text_hash` for future duplicate suppression.

---

## 19. Access Control

For MVP, only one owner should use the bot.

Every bot command and callback must check:

```text
telegram_user_id == OWNER_TELEGRAM_ID
```

If another user opens the bot:

```text
Access denied.
```

---

## 20. Commands and Buttons

Required commands:

```text
/start
/channels
/add_channel
/remove_channel
/settings
```

Recommended settings:

```text
Current threshold: 70
Change threshold
Show learned preferences
Show last processed posts
```

For MVP, the most important part is the monitoring and feedback loop.

---

## 21. Admin Debug Commands

Add simple debug commands for development.

### /preferences

Shows top positive and negative preferences.

Example:

```text
Top positive:
topic: AI agents +12
entity: n8n +9
channel_address: @some_channel +8

Top negative:
content_type: meme -20
tone: hype -12
channel_address: @bad_channel -8
```

### /last_scores

Shows the last 10 scored posts:

```text
84 @channel — tool_release — sent
62 @channel — news — not sent
23 @channel — meme — skipped
```

### /threshold 75

Changes score threshold.

---

## 22. Error Handling

Handle:

- invalid channel links;
- inaccessible private channels;
- Telegram rate limits;
- expired Telegram user session;
- LLM API timeout;
- invalid JSON from LLM;
- database errors;
- Telegram message sending errors.

If LLM returns invalid JSON:

1. Retry once with a stricter prompt.
2. If still invalid, mark post as `failed`.
3. Save error details to logs.

---

## 23. Logging Requirements

Log:

- worker start and finish;
- number of channels checked;
- number of new posts found;
- number of posts skipped by hard filters;
- number of posts sent;
- LLM errors;
- scoring errors;
- feedback events;
- preference updates.

Do not log secrets or session strings.

---

## 24. Suggested Implementation Plan

### Step 1. Add PostgreSQL

- Add PostgreSQL service.
- Add `DATABASE_URL`.
- Add migrations.
- Add database client.
- Create tables:
  - `users`
  - `channels`
  - `posts`
  - `user_feedback`
  - `user_preferences`
  - `processing_logs`

### Step 2. Move existing data/config to PostgreSQL

If current channels or filters are stored in memory, JSON, SQLite, or config files, migrate them to PostgreSQL.

At minimum, store:

- owner user;
- channels;
- last seen message ID;
- score threshold.

### Step 3. Implement post monitor worker

- Run every 5 minutes.
- Fetch new posts from active channels.
- Avoid old history on first run.
- Save posts to DB.
- Mark duplicates correctly.

### Step 4. Keep and improve hard filters

- Keep existing stop-word logic.
- Keep contextual filtering for memes and jokes if already implemented.
- Save skipped posts with skip reason.

### Step 5. Implement LLM feature extraction

- Add prompt from this document.
- Parse JSON strictly.
- Store result in `posts.features_json`.
- Add `channel_address` into features.

### Step 6. Implement scoring engine

- Implement deterministic scoring.
- Use `user_preferences`.
- Use `channels.channel_quality_weight`.
- Save `final_score`.
- Save `score_details_json`.

### Step 7. Implement sending

- If score >= threshold, send post immediately.
- Include source channel.
- Include source link.
- Include score.
- Include short summary.
- Include reason.
- Attach inline keyboard with 4 buttons in one row.
- Mark post as `sent`.

### Step 8. Implement feedback callbacks

- Parse callback data.
- Save or update `user_feedback`.
- Update `user_preferences`.
- Update channel preference and optionally `channels.channel_quality_weight`.
- Confirm the click to the user.

### Step 9. Add debug commands

- `/preferences`
- `/last_scores`
- `/threshold 75`

### Step 10. Test end-to-end

Test cases:

1. Add channel.
2. First run should not spam old history.
3. New post is collected.
4. Hard-filtered post is skipped.
5. Useful post gets features.
6. Score is calculated.
7. High-score post is sent.
8. Feedback button updates preferences.
9. Similar future post receives changed score.
10. Bad channel feedback lowers future posts from that channel.
11. LLM JSON error is handled.
12. Duplicate Telegram message is not processed twice.

---

## 25. Acceptance Criteria

The task is complete when:

- PostgreSQL is added and used as the main data store.
- The bot monitors channels every 5 minutes.
- New posts are saved to DB.
- Old channel history is not sent on first registration.
- Each post receives structured features.
- Channel address is included in features and scoring.
- Score is calculated by backend logic, not directly by LLM.
- User preferences influence scoring.
- Channel quality influences scoring.
- Posts above threshold are sent immediately.
- Every sent post has 4 inline buttons in one row:
  - 👍 Больше такого
  - 👎 Меньше такого
  - ⭐ Очень важно
  - 🗑 Скрывать такое
- Button clicks are saved in `user_feedback`.
- Button clicks update `user_preferences`.
- Feedback changes future scoring.
- Source link is included in every sent post.
- Debug commands exist for preferences and scores.
- Secrets are stored only in environment variables.
- The app can be started locally and in Docker.

---

## 26. Important Notes

Do not implement vector embeddings yet.

Do not build a digest feature now.

Do not train a custom model.

Do not let the LLM make the final send/not-send decision.

The LLM should only extract features.

The backend scoring engine should make the final decision.

The scoring system must be transparent and debuggable.
