"""One resolver per output field (company name, logo, MCC, address). Each is a list of steps
run by the shared cascade in cascade.py, and the registry of resolvers lives in this file.

Belongs here: the logic that decides a field's value from Evidence, using the ports in the
RunContext.

Doesn't belong here: provider-specific code. Resolvers reach models, search and geocoding only
through the ports.
"""
