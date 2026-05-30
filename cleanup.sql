DELETE FROM posts WHERE published_at IS NULL OR published_at < NOW() - INTERVAL '7 days';
