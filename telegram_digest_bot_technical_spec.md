# Technical Specification: Telegram Channel Digest Bot

## 1. Project Overview

The goal is to build a Telegram bot that collects posts from selected Telegram channels and generates a personalized digest twice per day.

The bot should work with the user's Telegram subscriptions or manually added Telegram channels. It should summarize relevant posts using the DeepSeek API and send the final digest to the user in Telegram.

The user should be able to manage channels, configure filters, and control which topics should be ignored or highlighted directly from the Telegram bot interface.

---

## 2. Core Use Case

The user subscribes to many Telegram channels and does not want to manually read all posts.

The bot should:

1. Collect new posts from selected Telegram channels.
2. Ignore irrelevant posts based on user-defined filters.
3. Highlight posts related to important topics.
4. Summarize the remaining useful content.
5. Send a digest twice per day.

---

## 3. Main Requirements

### 3.1 Telegram Channel Management

The bot must allow the user to:

- Add a Telegram channel by link or username.
- View the list of added channels.
- Remove a channel from the list.
- Enable or disable a channel without deleting it.
- Optionally assign a custom name or category to a channel.

Example commands or buttons:

- `Add channel`
- `My channels`
- `Remove channel`
- `Pause channel`
- `Resume channel`

---

### 3.2 Digest Schedule

The bot must generate and send digests twice per day.

Default schedule:

- Morning digest
- Evening digest

The exact time should be configurable in environment variables or in the database.

Example:

```env
MORNING_DIGEST_TIME=09:00
EVENING_DIGEST_TIME=19:00
TIMEZONE=Europe/Moscow
```

The system should only include posts that were published since the previous digest.

---

### 3.3 Post Collection

The bot should collect posts from added Telegram channels.

Important: Telegram Bot API cannot read arbitrary channel posts unless the bot is added as an admin or member where applicable. Therefore, for reading channels from the user's Telegram account, the implementation should use Telegram MTProto API through a user session.

Recommended libraries:

- Python: `Telethon`
- Node.js: `gramjs`

The user account session should be created once and then reused securely.

Required Telegram credentials:

```env
TELEGRAM_API_ID=
TELEGRAM_API_HASH=
TELEGRAM_USER_SESSION=
BOT_TOKEN=
```

The bot itself is used as the user interface, while MTProto user session is used to read posts.

---

### 3.4 Filtering System

The bot must support two types of filters:

#### Ignore Filters

These are topics, keywords, or post types that should be skipped.

Examples:

- advertisements
- giveaways
- job vacancies
- crypto spam
- motivational quotes
- reposts without useful content

#### Highlight Filters

These are topics that should be prioritized and emphasized in the digest.

Examples:

- AI agents
- automation
- Telegram bots
- n8n
- business ideas
- coding tools
- education technology

The user should be able to edit filters directly in the bot.

Example commands or buttons:

- `Ignore topics`
- `Highlight topics`
- `Add ignore topic`
- `Remove ignore topic`
- `Add highlight topic`
- `Remove highlight topic`

---

## 4. Summarization Logic

The bot should use DeepSeek API to summarize collected posts.

The user already has a DeepSeek API key.

Required environment variable:

```env
DEEPSEEK_API_KEY=
```

Recommended model:

```env
DEEPSEEK_MODEL=deepseek-chat
```

The summarization process should work in stages:

### Stage 1: Pre-filtering

Before sending posts to the LLM, the system should remove obviously irrelevant posts using simple rules:

- Empty posts
- Very short posts
- Duplicate posts
- Posts containing only links
- Posts matching ignore keywords

### Stage 2: LLM Classification

For unclear posts, the system should ask the LLM to classify them:

- `ignore`
- `normal`
- `highlight`

The classifier should consider the user's ignore and highlight filters.

### Stage 3: Digest Generation

The final digest should be generated from posts marked as `normal` and `highlight`.

Highlighted posts should appear in a separate section or be visually marked.

---

## 5. Digest Format

The digest should be concise, readable, and useful.

Recommended structure:

```markdown
# Telegram Digest

## Top Highlights

1. **Topic / Channel**
   Short summary of the most important idea.
   Link to the original post.

2. **Topic / Channel**
   Short summary.
   Link to the original post.

## Other Useful Posts

- Summary of post 1
- Summary of post 2
- Summary of post 3

## Skipped Noise

Optional short note:
"Skipped 37 posts: ads, reposts, short messages, irrelevant updates."
```

Each item should include:

- Channel name
- Short summary
- Original post link, if available
- Optional reason why it was highlighted

---

## 6. User Interface in Telegram Bot

The bot should be controlled through Telegram inline buttons and commands.

### Main Menu

Buttons:

- `Generate digest now`
- `My channels`
- `Add channel`
- `Filters`
- `Digest schedule`
- `Settings`

### Channel Management

The user should be able to:

- Add a channel by sending a link.
- See all added channels.
- Delete a channel.
- Pause/resume a channel.

### Filter Management

The user should be able to:

- View ignored topics.
- View highlighted topics.
- Add a new ignored topic.
- Add a new highlighted topic.
- Delete existing filters.

### Manual Digest

The user should be able to request a digest manually at any time.

Button:

- `Generate digest now`

---

## 7. Data Storage

A database is required.

Recommended option for a small MVP:

- SQLite

Recommended option for production:

- PostgreSQL

### Required Tables

#### users

Stores Telegram bot users.

Fields:

- `id`
- `telegram_id`
- `created_at`
- `timezone`
- `morning_digest_time`
- `evening_digest_time`

#### channels

Stores tracked Telegram channels.

Fields:

- `id`
- `user_id`
- `channel_username`
- `channel_title`
- `channel_link`
- `is_active`
- `created_at`

#### filters

Stores ignore and highlight filters.

Fields:

- `id`
- `user_id`
- `type` — `ignore` or `highlight`
- `value`
- `created_at`

#### posts

Stores collected posts to avoid duplicates.

Fields:

- `id`
- `channel_id`
- `telegram_message_id`
- `text`
- `post_link`
- `published_at`
- `classification`
- `summary`
- `created_at`

#### digests

Stores generated digests.

Fields:

- `id`
- `user_id`
- `period_start`
- `period_end`
- `content`
- `created_at`
- `sent_at`

---

## 8. Architecture

Recommended MVP architecture:

```text
Telegram Bot UI
      |
      v
Backend Application
      |
      |-- Telegram Bot API
      |-- Telegram MTProto Client
      |-- DeepSeek API
      |-- Scheduler
      |-- Database
```

### Components

#### Telegram Bot

Handles:

- User commands
- Inline buttons
- Settings
- Sending digests

#### Telegram Reader

Handles:

- Connecting through MTProto
- Reading posts from selected channels
- Saving new posts to the database

#### Digest Worker

Handles:

- Fetching unsummarized posts
- Applying filters
- Calling DeepSeek API
- Generating digest text

#### Scheduler

Handles:

- Running digest generation twice per day
- Sending scheduled digests

---

## 9. Suggested Tech Stack

### Option A: Python

Recommended for faster MVP.

- Python 3.11+
- Aiogram for Telegram Bot API
- Telethon for Telegram MTProto
- APScheduler for scheduled jobs
- SQLite or PostgreSQL
- SQLAlchemy
- Docker

### Option B: Node.js / TypeScript

Recommended if the existing project ecosystem is mostly TypeScript.

- Node.js 20+
- Telegraf or grammY for Telegram Bot API
- gramjs for Telegram MTProto
- node-cron or BullMQ for jobs
- SQLite or PostgreSQL
- Prisma ORM
- Docker

---

## 10. Hosting

The project requires a backend process that can run continuously or on a schedule.

GitHub Pages is not suitable because it only hosts static websites.

Vercel is not ideal for this use case because persistent Telegram user sessions, background jobs, and scheduled workers are harder to maintain there.

Recommended hosting options:

### Free or Low-Cost MVP

- Render free/low-cost web service
- Railway
- Fly.io
- Oracle Cloud Free Tier
- A small VPS

### Best Practical Option

A small VPS with Docker is the most reliable option.

The app can run as:

```text
bot container
worker container
database container
```

For a simple MVP, bot and worker can be one container.

---

## 11. Security Requirements

The project will handle sensitive Telegram account access.

Security rules:

- Never hardcode API keys in the code.
- Store all secrets in environment variables.
- Do not commit `.env` files to GitHub.
- Encrypt or carefully protect the Telegram user session.
- Restrict bot access to the owner only, at least in MVP.
- Store only necessary post data.
- Add logs, but do not log private secrets or session strings.

Recommended environment variables:

```env
BOT_TOKEN=
TELEGRAM_API_ID=
TELEGRAM_API_HASH=
TELEGRAM_USER_SESSION=
DEEPSEEK_API_KEY=
DATABASE_URL=
OWNER_TELEGRAM_ID=
TIMEZONE=
MORNING_DIGEST_TIME=
EVENING_DIGEST_TIME=
```

---

## 12. Access Control

For MVP, the bot should only work for one Telegram user.

The bot must check:

```text
message.from.id == OWNER_TELEGRAM_ID
```

If another person opens the bot, it should reply:

```text
Access denied.
```

Multi-user support can be added later.

---

## 13. Error Handling

The bot should handle:

- Invalid Telegram channel links
- Private channels without access
- Telegram rate limits
- DeepSeek API errors
- Empty digest periods
- Database errors
- Expired Telegram user session
- Network errors

If there are no useful posts, the bot should send:

```text
No useful posts found for this period.
```

---

## 14. Logging

The system should log:

- Bot startup
- Added/removed channels
- Number of collected posts
- Number of ignored posts
- DeepSeek API errors
- Digest generation results
- Digest delivery status

Logs should not contain secrets.

---

## 15. MVP Scope

The first version should include:

1. Telegram bot interface.
2. Owner-only access.
3. Add/list/remove channels.
4. Store channels in database.
5. Read posts via Telegram MTProto.
6. Store collected posts.
7. Ignore and highlight filters.
8. DeepSeek-based summarization.
9. Manual digest generation.
10. Scheduled digest twice per day.
11. Send digest in Telegram.

---

## 16. Future Improvements

Possible later features:

- Web dashboard
- Multi-user support
- PDF digest export
- Digest by topic
- Separate digests for different channel categories
- AI-generated tags
- Semantic filtering using embeddings
- Voice digest
- Integration with Notion, Google Docs, or email
- Analytics: top channels, useful/noisy ratio
- Weekly long-form digest

---

## 17. Example DeepSeek Prompt for Classification

```text
You are a Telegram post classifier.

User ignore topics:
{{ignore_topics}}

User highlight topics:
{{highlight_topics}}

Classify the following Telegram post as one of:
- ignore
- normal
- highlight

Return JSON only:
{
  "classification": "ignore | normal | highlight",
  "reason": "short explanation"
}

Post:
{{post_text}}
```

---

## 18. Example DeepSeek Prompt for Digest Generation

```text
You are an assistant that creates concise and useful Telegram digests.

The user wants to save time and only read meaningful updates.

User highlight topics:
{{highlight_topics}}

Create a digest from the following posts.

Rules:
- Write in Russian.
- Be concise.
- Group related posts by topic.
- Put the most important posts first.
- Mark highlighted posts clearly.
- Include original post links when available.
- Ignore noise and repetition.
- Do not invent facts.

Posts:
{{posts}}
```

---

## 19. Definition of Done

The project is considered complete when:

- The user can start the bot.
- The bot accepts only the owner.
- The user can add Telegram channels by link.
- The bot can read new posts from those channels.
- The user can configure ignore and highlight filters.
- The user can request a digest manually.
- The bot sends automatic digests twice per day.
- The digest is generated through DeepSeek API.
- The bot stores processed posts and does not duplicate them.
- The project can be deployed with Docker.
- All required secrets are configured through environment variables.

---

## 20. Recommended First Development Milestone

Build a minimal working prototype:

1. Create Telegram bot.
2. Add owner-only access.
3. Implement `/start`.
4. Implement channel adding.
5. Save channels to SQLite.
6. Connect Telegram user session via Telethon or gramjs.
7. Read the last 20 posts from one channel.
8. Send them to DeepSeek.
9. Return a manual digest in Telegram.

After this works, add scheduled digest generation and filter management.
