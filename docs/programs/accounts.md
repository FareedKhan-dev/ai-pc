# Accounts

## Accounts: invoices, books, sales tax; QuickBooks, TallyPrime, Xero, Zoho Books and FBR (programmatic, official APIs)

```
ai-pc accounts talk -m "invoice for Ali Traders: 2 LED TV 55 at 85,000 each, 18% tax, due in 15 days" -m "yes"
ai-pc accounts talk -m "Ali Traders paid 1.5 lakh by bank and deducted 4,000 tax" -m "yes" -m "who owes me money?" -m "profit this month"
ai-pc accounts talk -m "send everything to tally" -m "yes"         (or quickbooks, xero, zoho)
ai-pc accounts talk -m "post invoice 3 to FBR" -m "yes"            (FBR Digital Invoicing: validated first, then FBR's number and QR code on the PDF)
ai-pc accounts steps xero | connect xero                           (steps quickbooks / tally / zoho / fbr)
```

The books on this PC are the record (double entry in SQLite, exact paisa, Pakistan's July-June year, 18% sales tax per
line, 4% further tax for buyers without an STRN, income tax withheld, stock at average cost, gapless numbers, voids by
reversing entries, sales tax invoices as PDF, every change checked). The accounting software people already use gets a
copy: each document goes once and is read back total for total; every part (a payment per invoice, an allocation) is
remembered the moment it exists and looked for before a new try, so a lost answer never makes a duplicate; a document
cancelled here is cancelled there.

| System | How | Notes |
|---|---|---|
| Xero | Accounting API, PKCE app (no secret), http://localhost:3009/callback | Free Starter developer tier (1,000 calls a day); Idempotency-Key on every create; tax rate 'Sales Tax 18%' made once |
| Zoho Books | API v3, Self Client code pasted once | Free plan 1,000 calls a day; further tax as a tax group; no idempotency key, so nothing is retried blindly |
| QuickBooks Online | Accounting API v75, OAuth with client secret | Sandbox signs in on localhost; production needs an HTTPS redirect (paste the address); requestid on every write; tax codes under agency FBR |
| TallyPrime | XML gateway on port 9000, UTF-16, no key | Masters made only when missing (never alters yours); REMOTEID makes a resend an update; item invoices for stock |
| FBR Digital Invoicing | PRAL DI API v1.12, Bearer token | Validated first, posted on yes, never posted twice blindly; needs 1-3 fixed IPs approved by PRAL |

Measured (2026-10-04): [tests/integration/test_accounts.py](../../tests/integration/test_accounts.py) 52/52 (books, documents, rules, chat);
[tests/integration/accounts_conversations.py](../../tests/integration/accounts_conversations.py) 11/11 turns ($0.0005);
[tests/integration/test_accounts_systems.py](../../tests/integration/test_accounts_systems.py) 81/81 against fakes of each API
([tests/integration/accounts_fakes.py](../../tests/integration/accounts_fakes.py)): lost answers, a failure part-way, expired sign-ins, limits, voids. Live use waits on your keys.
