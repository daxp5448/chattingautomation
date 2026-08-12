"""Niche-template seed modules -- one module per NicheTemplate.code, each exporting a
module-level `TEMPLATE` dict matching app/models/niche_template.py's column shapes
exactly. Not imported automatically anywhere; a super-admin bootstrap/seed script (or a
test, see app/tests/test_niche_salon.py) is expected to import the specific niche module
it needs and construct/persist a NicheTemplate row from its `TEMPLATE` dict.
"""
