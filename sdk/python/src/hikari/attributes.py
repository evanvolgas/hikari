"""Hikari span attribute constants.

All attributes are prefixed with ``hikari.`` and follow OTel semantic conventions
for custom attribute namespaces.
"""

PIPELINE_ID = "hikari.pipeline_id"
STAGE = "hikari.stage"
MODEL = "hikari.model"
PROVIDER = "hikari.provider"
TOKENS_INPUT = "hikari.tokens.input"
TOKENS_OUTPUT = "hikari.tokens.output"
COST_INPUT = "hikari.cost.input"
COST_OUTPUT = "hikari.cost.output"
COST_TOTAL = "hikari.cost.total"
