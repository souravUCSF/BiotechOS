"""Processors — specialized, schema-bound units of model work triggered by a
document/event. Each is a `prompt + output schema + validator` bundle, invoked as
a single constrained call (not an autonomous agent). Subtypes by verb:

    extractor  read → structured data   (quote, biological data)
    generator  draft → artifact         (PO from a quote)          [later]
    screener   judge → assessment       (legal/contract review)    [later]

The output schema is fixed; the input format is not — this is how one processor
handles the many formats a real quote/invoice/contract arrives in.
"""
