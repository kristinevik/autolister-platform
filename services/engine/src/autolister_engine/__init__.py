"""Autolister pricing engine.

Reads the market, decides how every managed position should be listed, and
publishes sealed instructions for the signer. It never holds a wallet key: its
service account has no access to wallet secrets.
"""
