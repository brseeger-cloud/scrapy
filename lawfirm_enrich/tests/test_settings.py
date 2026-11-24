from scrapy.settings import Settings

from lawfirm_enrich import settings as project_settings


def test_required_settings():
    s = Settings()
    s.setmodule(project_settings)
    assert s.getbool("ROBOTSTXT_OBEY") is True
    assert s.getbool("AUTOTHROTTLE_ENABLED") is True
    assert s.getfloat("DOWNLOAD_DELAY") == 2
    assert s.get("USER_AGENT") == "LawAuditResearch (audit@lawaudit.com.au)"
    assert s.getint("RETRY_TIMES") == 2
    assert s.getint("DOWNLOAD_TIMEOUT") == 20
    assert s.getint("LAWFIRM_MAX_PAGES") == 6
    assert s.getbool("HTTPCACHE_ENABLED") is False
