"""Brevo email campaigns: the work is in mailchimp.py (one module reads requests for both services); this entry gives
Brevo its own 'ai-pc apps steps brevo' and 'ai-pc apps connect brevo'."""
from ai_pc.apps import mailchimp

NAME, LABEL = "brevo", "Brevo email campaigns (see mailchimp)"
EXAMPLES = ["brevo lists"]
APP = mailchimp.BREVO_APP


def connect(values, transport=None, store=None):
    return mailchimp.connect(values, transport, store, which="brevo")


def parse(text, ctx):
    return None  # mailchimp.parse reads 'brevo' requests too
