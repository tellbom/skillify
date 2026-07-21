-- Verified artifact scan facts; run metrics remain derived from endpoint task events.

ALTER TABLE skill_index ADD governance CLOB;
UPDATE skill_index SET governance = '{}' WHERE governance IS NULL;
ALTER TABLE skill_index MODIFY governance CLOB NOT NULL;
