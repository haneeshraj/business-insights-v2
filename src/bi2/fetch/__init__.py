"""Loading pages: the Playwright fetcher for rendered pages and screenshots, the plain-HTTP
fetcher for secondary pages, and the DNS-based URL safety check that both use.

Belongs here: code that loads pages and returns PageSnapshots, behind the Fetcher port.

Doesn't belong here: reading what a page says (evidence/) or deciding anything about it.
"""
