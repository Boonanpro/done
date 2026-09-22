"""URL matching of saved credentials: a shared public suffix (co.jp) is not a shared site."""
from app.services.credentials_service import _base_domain, _domains_match


def test_second_level_public_suffix_is_part_of_the_tld():
    assert _base_domain('shinkansen1.jr-central.co.jp') == 'jr-central.co.jp'
    assert _base_domain('www.netbk.co.jp') == 'netbk.co.jp'
    assert _base_domain('accounts.google.com') == 'google.com'
    assert _base_domain('login.example.co.uk') == 'example.co.uk'


def test_two_co_jp_sites_do_not_match_each_other_but_subdomains_of_one_site_do():
    assert not _domains_match('shinkansen1.jr-central.co.jp', 'www.netbk.co.jp')
    assert _domains_match('shinkansen1.jr-central.co.jp', 'shinkansen2.jr-central.co.jp')
    assert _domains_match('www.instagram.com', 'instagram.com')
