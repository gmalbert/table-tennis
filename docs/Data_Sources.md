🏓 Table Tennis Data Sources
1. ITTF Official Data — results.ittf.link
Type: Scrapable website
The official ITTF results portal at results.ittf.link provides WTT results, statistics, head-to-head records, player profiles, world rankings, and historical data — this is gold for official match results going back years. No official API, but the site is structured and scrapable with Python (requests + BeautifulSoup or Playwright for JS-rendered pages). There's also a GitHub project (romanzdk/ittf-data-scrape) specifically built for scraping ITTF data — a strong starting point.
What you get: Official match results, player rankings, H2H records, tournament brackets, WTT events.

2. Flashscore — flashscore.com/table-tennis
Type: Scrapable / Apify actors
Flashscore explicitly supports table tennis in its scraper ecosystem, alongside tennis, badminton, darts, snooker, and more. Flashscore has no official API, but there are multiple ways to get data:

DIY scraping via Playwright/Puppeteer (it's JS-heavy)
Apify actors — the Flashscore Results actor extracts full head-to-head history between two players/teams including dates, scores, competition, and team details, returning up to 20 fields per historical match in structured JSON
A typical Apify run costs under $0.01 on the free tier — very cheap for bulk historical pulls

What you get: Match results, live scores, set-by-set scores, tournament metadata, head-to-head history, player rankings.

3. SofaScore (Unofficial API)
Type: Reverse-engineered API / scraping
There's an open GitHub project (robssson/Table-Tennis) focused on scraping table tennis data from SofaScore, displaying match results from many various tournaments with up to 1,000 matches, including match statistics per match ID.
SofaScore has well-documented unofficial API endpoints (e.g. api.sofascore.com/api/v1/sport/table-tennis/events/...) that return clean JSON — many developers use these directly in projects without needing a scraper at all. It's the most developer-friendly free source.
What you get: Match results, set scores, player stats, tournament structures, live data.

4. OddsPortal — oddsportal.com/table-tennis
Type: Scrapable (critical for betting)
OddsPortal covers table tennis results across leagues and competitions worldwide, with historical odds from those results also available — including odds history and final outcomes across multiple bookmakers. This is the key source if you want closing odds + results together, which is the foundation of any serious betting model.
There's an Apify actor for OddsPortal that supports extracting win/draw/lose odds, over/under, Asian handicap, and more across any sport including table tennis, with support for decimal, fractional, moneyline, and other formats.
What you get: Historical match odds (opening + closing) from 20+ bookmakers, results, over/under lines, handicap odds.

5. BetExplorer
Type: Scrapable
Another OddsPortal-style site with table tennis historical odds and results. Less JavaScript-heavy than OddsPortal, making it easier to scrape directly with requests/BeautifulSoup. Good for cross-referencing odds.

📊 Recommended Stack for Your Site
LayerSourceDataMatch results + H2HITTF results.ittf.linkOfficial records, rankingsLive + recent scoresSofaScore unofficial APIReal-time, clean JSONDeep history + set scoresFlashscore via ApifyBulk historical pullsOdds (the betting layer)OddsPortal (Apify or DIY)Historical closing odds
Tech tip: Combine SofaScore's unofficial JSON API (no scraper needed, just HTTP requests) with OddsPortal Apify actors for odds. Store everything in a Postgres or SQLite database. The ITTF scraper handles official player rankings and tournament trees.
Want me to help you build out the scraping scripts, design the database schema, or start scaffolding the analysis site itself?