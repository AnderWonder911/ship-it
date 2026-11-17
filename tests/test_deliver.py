import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "delivery"))
import deliver as d  # noqa: E402

SINCE = 1_000
MIN = 18_000


def item(id_, amount, comment="", t=2_000, desc="Від: Test"):
    return {"id": id_, "amount": amount, "comment": comment, "time": t, "description": desc}


def test_extract_email_variants():
    assert d.extract_email("anna@gmail.com") == "anna@gmail.com"
    assert d.extract_email("my email: Anna.B@Gmail.com thanks!") == "anna.b@gmail.com"
    assert d.extract_email("anna @ gmail.com") == "anna@gmail.com"
    assert d.extract_email("anna at gmail dot com") == "anna@gmail.com"
    assert d.extract_email("", None, "x@y.io") == "x@y.io"
    assert d.extract_email("no email here") is None


def test_valid_sale():
    sales, un = d.classify([item("a", 20_000, "buyer@mail.com")], set(), SINCE, MIN)
    assert sales == [{"id": "a", "email": "buyer@mail.com", "amount": 20_000, "time": 2_000}]
    assert un == []


def test_foreign_card_amount_above_min():
    sales, _ = d.classify([item("a", 18_500, "b@b.de")], set(), SINCE, MIN)
    assert len(sales) == 1


def test_below_price_goes_to_review():
    sales, un = d.classify([item("a", 5_000, "b@b.de")], set(), SINCE, MIN)
    assert sales == [] and un[0]["reason"] == "below price"


def test_no_email_goes_to_review():
    sales, un = d.classify([item("a", 20_000, "thanks!")], set(), SINCE, MIN)
    assert sales == [] and un[0]["reason"] == "no email in comment"


def test_duplicate_is_ignored():
    sales, un = d.classify([item("a", 20_000, "b@b.de")], {"a"}, SINCE, MIN)
    assert sales == [] and un == []


def test_old_payment_before_launch_ignored():
    sales, un = d.classify([item("a", 20_000, "b@b.de", t=500)], set(), SINCE, MIN)
    assert sales == [] and un == []


def test_withdrawal_ignored():
    sales, un = d.classify([item("a", -20_000, "b@b.de")], set(), SINCE, MIN)
    assert sales == [] and un == []


def test_jar_matching():
    assert d.jar_matches({"sendId": "jar/67pBy3mtKn"}, "67pBy3mtKn")
    assert d.jar_matches({"sendId": "67pBy3mtKn"}, "67pBy3mtKn")
    assert not d.jar_matches({"sendId": "jar/OTHER"}, "67pBy3mtKn")


def test_delivery_email_has_attachment():
    m = d.build_delivery("b@b.de", "me@gmail.com", b"# pack")
    atts = list(m.iter_attachments())
    assert m["To"] == "b@b.de" and atts[0].get_filename() == d.PRODUCT_FILENAME
    assert atts[0].get_content() == "# pack"


def test_alert_lists_sales_and_reviews():
    m = d.build_alert("me@gmail.com", [{"amount": 20_000, "email": "b@b.de"}],
                      [{"amount": 5_000, "reason": "below price", "comment": "hi", "description": "x"}])
    body = m.get_content()
    assert "b@b.de" in body and "below price" in body and m["Subject"].startswith("💰")
