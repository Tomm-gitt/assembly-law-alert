"""Compatibility entrypoints. All notifications are persisted and gated by HUB."""
from hub_notify import send_new_bills, send_status_alerts


def _send(text):
    raise RuntimeError("Direct Telegram sends are disabled; submit an identified event to HUB")
