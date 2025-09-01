SHOW TABLES;
DROP TABLE article;
DROP TABLE scrape_job;

SELECT * FROM article;
SELECT * FROM scrape_job;

UPDATE scrape_job SET status = 'finished', finished_at = NOW() WHERE status = 'running';

SELECT COUNT(*) FROM article;

SELECT * FROM article ORDER BY id DESC;

-- Preview cleaned author values (no write)
SELECT id, author AS raw_author,
  TRIM(
    REGEXP_REPLACE(
      REPLACE(author, CHAR(160), ' '),
      '^\s*(?:by\s+)?(.+?)(?:\s+(?:share|x \(formerly|viber|email|january|february|march|april|may|june|july|august|september|october|november|december)\b).*|\s+\d{4}.*$',
      '\\1',
      1, 0, 'i'
    )
  ) AS clean_author
FROM article
WHERE author IS NOT NULL
LIMIT 50;