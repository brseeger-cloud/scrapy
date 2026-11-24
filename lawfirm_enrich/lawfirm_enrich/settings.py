# Scrapy settings for the lawfirm_enrich project.
# See README.md for what each LAWFIRM_* setting does.

BOT_NAME = "lawfirm_enrich"
SPIDER_MODULES = ["lawfirm_enrich.spiders"]
NEWSPIDER_MODULE = "lawfirm_enrich.spiders"

# --- Identification & politeness (required by the brief) -------------------
USER_AGENT = "LawAudit (audit@lawaudit.com.au)"
ROBOTSTXT_OBEY = True

DOWNLOAD_DELAY = 2  # seconds between requests to the same site
RANDOMIZE_DOWNLOAD_DELAY = False  # keep the delay at a true 2s minimum
AUTOTHROTTLE_ENABLED = True
AUTOTHROTTLE_START_DELAY = 2
AUTOTHROTTLE_MAX_DELAY = 30
AUTOTHROTTLE_TARGET_CONCURRENCY = 1.0

CONCURRENT_REQUESTS = 16  # across different firms
CONCURRENT_REQUESTS_PER_DOMAIN = 1  # never more than one request at a time to a site

RETRY_ENABLED = True
RETRY_TIMES = 2
DOWNLOAD_TIMEOUT = 20
DNS_TIMEOUT = 20

REDIRECT_MAX_TIMES = 5
DOWNLOAD_MAXSIZE = 5 * 1024 * 1024  # skip anything over 5 MB
DOWNLOAD_WARNSIZE = 2 * 1024 * 1024
DOWNLOADER_MIDDLEWARE_RESPONSE_EXCEPTIONS = True

# --- Privacy ----------------------------------------------------------------
# No page content is cached to disk (pages contain email addresses).
HTTPCACHE_ENABLED = False
COOKIES_ENABLED = False
TELNETCONSOLE_ENABLED = False
# INFO keeps scraped items and page bodies out of the log.
LOG_LEVEL = "INFO"

# --- Pipelines --------------------------------------------------------------
ITEM_PIPELINES = {
    "lawfirm_enrich.pipelines.DoNotContactPipeline": 100,
    "lawfirm_enrich.pipelines.EmailScrubPipeline": 200,
    "lawfirm_enrich.pipelines.MasterListPipeline": 800,
    "lawfirm_enrich.pipelines.ExcelExportPipeline": 900,
}

# --- Project settings (override with -s NAME=value or run.py options) -------
LAWFIRM_INPUT_CSV = "firms.csv"
LAWFIRM_DNC_CSV = "do_not_contact.csv"
LAWFIRM_UNSUBSCRIBED_CSV = "unsubscribed.csv"  # email addresses that unsubscribed (optional file)
LAWFIRM_OUTPUT_XLSX = "output/firms_enriched.xlsx"
LAWFIRM_FAILED_CSV = "output/failed_sites.csv"
LAWFIRM_MASTER_XLSX = "data/master.xlsx"  # set to "" to not keep a master list
LAWFIRM_SKIP_CRAWLED_WITHIN_DAYS = 0  # >0: skip firms the master list shows were crawled recently
LAWFIRM_MAX_PAGES = 6  # home + about + team/our-people + contact, hard cap per site
LAWFIRM_TIMEZONE = "Australia/Sydney"  # used for the date_collected column

FEED_EXPORT_ENCODING = "utf-8"
