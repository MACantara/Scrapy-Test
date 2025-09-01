SHOW TABLES;
DROP TABLE article;
DROP TABLE scrape_job;

SELECT * FROM article;
SELECT * FROM scrape_job;	

UPDATE scrape_job SET status = 'finished', finished_at = NOW() WHERE status = 'running';
UPDATE scrape_job SET status = 'finished', finished_at = NOW() WHERE status = 'running' AND items_count = 0;

SELECT COUNT(*) FROM article;

SELECT * FROM article ORDER BY id DESC;

-- Preview cleaned author values for PNA (no writes)
SELECT
  id,
  author AS raw_author,
  NULLIF(
    TRIM(
      REGEXP_REPLACE(
        REGEXP_REPLACE(
          REGEXP_REPLACE(
            CONVERT(REPLACE(CONVERT(author USING latin1), CHAR(160), ' ') USING utf8mb4),
            '^\\s*by\\s+',
            '',
            1, 0, 'i'
          ),
          '\\s+(January|February|March|April|May|June|July|August|September|October|November|December)\\s+\\d{1,2},\\s*\\d{4}(?:,\\s*\\d{1,2}:\\d{2}\\s*(?:am|pm))?',
          '',
          1, 0, 'i'
        ),
        '\\s+(share|x \\(formerly|viber|email)\\b.*$',
        '',
        1, 0, 'i'
      )
    ),
    ''
  ) AS clean_author
FROM article
WHERE author IS NOT NULL
  AND source = 'pna'
LIMIT 50;

-- Apply cleanup to articles from PNA (MySQL 8+)
UPDATE article
SET author = NULLIF(
  TRIM(
    REGEXP_REPLACE(
      REGEXP_REPLACE(
        REGEXP_REPLACE(
          CONVERT(REPLACE(CONVERT(author USING latin1), CHAR(160), ' ') USING utf8mb4),
          '^\\s*by\\s+',
          '',
          1, 0, 'i'
        ),
        '\\s+(January|February|March|April|May|June|July|August|September|October|November|December)\\s+\\d{1,2},\\s*\\d{4}(?:,\\s*\\d{1,2}:\\d{2}\\s*(?:am|pm))?',
        '',
        1, 0, 'i'
      ),
      '\\s+(share|x \\(formerly|viber|email)\\b.*$',
      '',
      1, 0, 'i'
    )
  ),
  ''
)
WHERE author IS NOT NULL
  AND source = 'pna';
  
-- Manila Bulletin Debugging
SELECT * FROM article WHERE source = "manilabulletin" or source = "Manila Bulletin" ORDER BY id DESC;
SELECT COUNT(*) FROM article WHERE source LIKE "%manila%";
SELECT * FROM article WHERE url = "https://mb.com.ph/2025/09/01/pdeg-p605-m-worth-of-shabu-seized-in-zamboanga-city-3-arrested";
DELETE FROM article WHERE source = "manilabulletin" OR source = "Manila Bulletin";