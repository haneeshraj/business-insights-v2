"""Builds a RunContext from real implementations: `build_local_context` for the terminal app
and `build_hosted_context` for the website's workers.

This is where infrastructure is chosen and connected to the ports. Only entry points import
this module; logic and infrastructure never do.
"""
