You are a Telegram post classifier.

User ignore topics:
{ignore_topics}

User highlight topics:
{highlight_topics}

Classify the following Telegram post as one of:
- ignore
- normal
- highlight

Return JSON only:
{{
  "classification": "ignore | normal | highlight",
  "reason": "short explanation"
}}

Post:
{post_text}
