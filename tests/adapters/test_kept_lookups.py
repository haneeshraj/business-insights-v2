"""Tests for keeping knowledge-base answers, for runs on saved pages."""

from pathlib import Path

from bi2.adapters.local.lookups import KeptLookups
from bi2.core.models import KnownBusiness
from tests.fakes import FakeKnowledge

NO_FRILLS = KnownBusiness(item="Q3342407", name="No Frills")


async def test_an_answer_is_looked_up_once_and_kept(tmp_path: Path) -> None:
    online = FakeKnowledge({"nofrills.ca": NO_FRILLS})
    first = await KeptLookups(online, tmp_path).business_with_website("https://www.nofrills.ca/")
    offline = FakeKnowledge(reachable=False)  # only a kept answer will do
    again = await KeptLookups(offline, tmp_path).business_with_website("https://nofrills.ca/en")
    assert first == again == NO_FRILLS
    assert offline.asked == []


async def test_no_such_business_is_kept_too(tmp_path: Path) -> None:
    await KeptLookups(FakeKnowledge(), tmp_path).business_with_website("https://example-cafe.ca/")
    offline = FakeKnowledge(reachable=False)
    found = await KeptLookups(offline, tmp_path).business_with_website("https://example-cafe.ca/")
    assert found is None
    assert offline.asked == []
