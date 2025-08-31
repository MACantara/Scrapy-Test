SHOW TABLES;
DROP TABLE article;
DROP TABLE scrape_job;

SELECT * FROM article;
SELECT * FROM scrape_job;

UPDATE scrape_job SET status = 'finished', finished_at = NOW() WHERE status = 'running';

SELECT COUNT(*) FROM article;