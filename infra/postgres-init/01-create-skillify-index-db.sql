-- Skillify's own tables (T2.2 index, later M5 comments/leaderboard) live in a separate
-- database within the same PostgreSQL instance Forgejo uses, rather than a second server —
-- PLAN.md §2 lists a single shared "PostgreSQL" component for "索引、评论、排行榜、上报事件".
CREATE DATABASE skillify_index;
