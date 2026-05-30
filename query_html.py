import sqlite3
import html
import json

DB_PATH = "/app/data/digest_bot.db"
OUT_PATH = "/app/data/posts_report.html"

db = sqlite3.connect(DB_PATH)
db.row_factory = sqlite3.Row

cur = db.execute(
    "SELECT id, channel_id, telegram_message_id, "
    "substr(text,1,200) as text_preview, "
    "classification, summary, published_at, post_link "
    "FROM posts ORDER BY published_at DESC LIMIT 100"
)
rows = cur.fetchall()

with open(OUT_PATH, "w", encoding="utf-8") as f:
    f.write("""<!DOCTYPE html>
<html lang="ru">
<head>
<meta charset="utf-8">
<title>Digest Bot — Posts</title>
<style>
body { font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif; margin: 20px; background: #f5f5f5; }
h1 { color: #333; }
.summary { margin-bottom: 10px; color: #666; }
table { border-collapse: collapse; width: 100%; background: white; box-shadow: 0 1px 3px rgba(0,0,0,0.1); }
th { background: #2c3e50; color: white; padding: 10px 8px; text-align: left; font-size: 13px; }
td { padding: 8px; border-bottom: 1px solid #eee; font-size: 13px; vertical-align: top; }
tr:hover { background: #f8f9fa; }
.preview { max-width: 400px; word-break: break-word; }
.link a { color: #3498db; text-decoration: none; font-weight: bold; }
.link a:hover { text-decoration: underline; }
.normal { color: #27ae60; }
.ignore { color: #e74c3c; }
.highlight { color: #f39c12; }
.stats { display: flex; gap: 20px; margin-bottom: 20px; }
.stat { background: white; padding: 12px 20px; border-radius: 6px; box-shadow: 0 1px 3px rgba(0,0,0,0.1); }
.stat .num { font-size: 28px; font-weight: bold; }
.stat .label { color: #888; font-size: 13px; }
</style>
</head>
<body>
<h1>Digest Bot — Посты в базе</h1>
""")

    stats = {"total": len(rows), "normal": 0, "ignore": 0, "highlight": 0}
    for r in rows:
        cls = r["classification"] or ""
        if cls in stats:
            stats[cls] += 1

    f.write('<div class="stats">')
    f.write('<div class="stat"><div class="num">{}</div><div class="label">Всего</div></div>'.format(stats["total"]))
    f.write('<div class="stat"><div class="num">{}</div><div class="label">Normal</div></div>'.format(stats["normal"]))
    f.write('<div class="stat"><div class="num">{}</div><div class="label">Ignore</div></div>'.format(stats["ignore"]))
    f.write('<div class="stat"><div class="num">{}</div><div class="label">Highlight</div></div>'.format(stats["highlight"]))
    f.write('</div>')

    f.write('<table>')
    f.write('<tr><th>ID</th><th>Ch</th><th>MsgID</th><th>Preview</th><th>Class</th><th>Published</th><th>Link</th></tr>')
    for r in rows:
        text = html.escape(r["text_preview"] or "")[:140]
        link = r["post_link"] or ""
        link_html = '<a href="{}" target="_blank">&#x2197;</a>'.format(html.escape(link)) if link else "-"
        cls = r["classification"] or "?"
        css_cls = cls if cls in ("normal", "ignore", "highlight") else ""
        pub = r["published_at"] or "-"
        if pub != "-" and len(pub) > 16:
            pub = pub[:16].replace(" ", "T")
        f.write('<tr>')
        f.write('<td>{}</td>'.format(r["id"]))
        f.write('<td>{}</td>'.format(r["channel_id"]))
        f.write('<td>{}</td>'.format(r["telegram_message_id"]))
        f.write('<td class="preview">{}</td>'.format(text))
        f.write('<td class="{}"><b>{}</b></td>'.format(css_cls, cls))
        f.write('<td>{}</td>'.format(pub))
        f.write('<td class="link">{}</td>'.format(link_html))
        f.write('</tr>\n')
    f.write('</table>')
    f.write('</body></html>')

print("OK: {}".format(OUT_PATH))
