# Ship It With Claude Code — store

Live site: https://anderwonder911.github.io/ship-it/

## How it works
1. **Site** (`index.html`, GitHub Pages). The buyer enters their email, copies it, and pays 200 ₴ to the monobank jar with the email in the comment.
2. **Delivery** (`.github/workflows/deliver.yml` → `delivery/deliver.py`). Every 10 minutes it reads the jar's statement through the monobank personal API. For each new payment of 180 ₴ or more with an email in the comment, it emails the buyer the pack and emails you a 💰 alert.
3. Payments with no email, or below the price, are emailed to you as ⚠️ so you can deliver them by hand.
4. `state/processed.json` remembers which transactions are done, so nobody gets the pack twice.

## Secrets (Settings → Secrets and variables → Actions)
| Name | What |
|---|---|
| `MONO_TOKEN` | token from https://api.monobank.ua/ (read-only) |
| `GMAIL_ADDRESS` | set in deliver.yml (andrew.kamyshin@gmail.com) |
| `GMAIL_APP_PASSWORD` | app password from https://myaccount.google.com/apppasswords |
| (product) | `delivery/product.enc`, the pack encrypted with the Gmail app password (spaces removed) |

## Common changes
- **Price:** edit the text in `index.html` and `?a=200`. For the minimum accepted amount, set the `MIN_AMOUNT_UAH` env var in `deliver.yml`.
- **Resend to someone:** remove their transaction id from `state/processed.json`, or just email the file by hand.
- **Run now:** Actions → Deliver orders → Run workflow (this also runs the tests).

## Tests
`pip install pytest && pytest -q`
