"""Tests for the URL helpers."""

from bi2.core.urls import (
    absolute_url,
    host,
    image_key,
    public_suffix,
    registrable_domain,
    same_site,
    social_key,
)


def test_absolute_url_resolves_web_links_only() -> None:
    page = "https://example-cafe.ca/menu/"
    assert absolute_url(page, "/contact") == "https://example-cafe.ca/contact"
    assert absolute_url(page, "drinks") == "https://example-cafe.ca/menu/drinks"
    assert absolute_url(page, "//cdn.example.com/a.png") == "https://cdn.example.com/a.png"
    for other in (
        "mailto:hi@example-cafe.ca",
        "tel:+14165550123",
        "javascript:void(0)",
        "#top",
        "",
    ):
        assert absolute_url(page, other) is None


def test_registrable_domain_knows_multi_part_suffixes() -> None:
    assert registrable_domain("https://shop.example.co.uk/x") == "example.co.uk"
    assert registrable_domain("https://www.example-cafe.ca/") == "example-cafe.ca"
    assert registrable_domain("http://127.0.0.1:8080/") == "127.0.0.1"
    assert public_suffix("https://shop.example.co.uk/") == "co.uk"
    assert host("https://WWW.Example-Cafe.ca/menu") == "example-cafe.ca"


def test_same_site_ignores_subdomains() -> None:
    assert same_site("https://example-cafe.ca/", "https://shop.example-cafe.ca/cart")
    assert not same_site("https://example-cafe.ca/", "https://example-cafe.com/")


def test_image_key_ignores_cdn_size_tags_and_transforms() -> None:
    shop = "https://shop.example.ca/cdn/shop/files/logo2"
    assert image_key(f"{shop}_150x.png?v=1") == image_key(f"{shop}_300x300.png")
    assert image_key(f"{shop}_{{width}}x.png") == image_key(f"http://www.{shop[8:]}.PNG")
    assert image_key("https://example.ca/wp-content/logo-300x100.png") == image_key(
        "https://example.ca/wp-content/logo.png"
    )
    wix = "https://static.wixstatic.com/media/5ef73e_5d6c~mv2.png"
    assert image_key(f"{wix}/v1/fill/w_240,h_63/logo.png") == image_key(wix)
    assert image_key(f"{shop}.png") != image_key(f"{shop}-white.png")


def test_social_key_names_the_profile() -> None:
    assert social_key("https://m.facebook.com/BarVolo/posts/123") == social_key(
        "https://facebook.com/barvolo"
    )
    assert (
        social_key("https://www.linkedin.com/company/acme/mycompany") == "linkedin.com/company/acme"
    )
    assert social_key("https://pinterest.ca/roots") == social_key(
        "https://www.pinterest.com/roots/"
    )
    assert social_key("https://facebook.com/profile.php?id=42") != social_key(
        "https://facebook.com/profile.php?id=7"
    )
