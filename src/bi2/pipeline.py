"""The per-site workflow: fetch the site, build its Evidence, run the resolvers and return a
SiteResult, emitting progress events along the way.

It depends only on core, evidence and resolvers, and gets everything else from the RunContext.
"""
