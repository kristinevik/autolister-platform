"""Autolister signer.

The only component with access to wallet keys, and deliberately the smallest.
It contains no pricing logic: it verifies the engine's instructions, re-checks
every price against the public order book, then signs and submits. It can sign
asks and cancel orders, and nothing else.
"""
