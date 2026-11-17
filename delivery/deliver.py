"""Poll the monobank jar, find new paid orders, email the product to buyers.

Runs on a GitHub Actions schedule. Secrets (env vars):
  MONO_TOKEN          monobank personal API token (read-only)
  GMAIL_ADDRESS       Gmail address that sends deliveries + receives sale alerts
  GMAIL_APP_PASSWORD  16-char Gmail app password
  PRODUCT_B64         base64 of the product markdown file
Optional:
  JAR_SEND_ID         defaults to 67pBy3mtKn
  MIN_AMOUNT_UAH      defaults to 180
  DRY_RUN=1           log what would happen, send nothing
"""
from __future__ import annotations

import base64
import json
import os
import re
import smtplib
import sys
import time
import urllib.error
import urllib.request
from email.message import EmailMessage
from pathlib import Path

API = "https://api.monobank.ua"
STATE_FILE = Path(__file__).resolve().parent.parent / "state" / "processed.json"
EMAIL_RE = re.compile(r"[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}")
LOOKBACK_SECONDS = 3 * 24 * 3600
PRODUCT_FILENAME = "ship-it-with-claude-code.md"
PRODUCT_NAME = "Ship It With Claude Code"


# ---------- pure helpers (unit tested) ----------

def extract_email(*texts: str | None) -> str | None:
    for t in texts:
        if not t:
            continue
        # tolerate "name at gmail dot com" and stray spaces around @ / .
        norm = re.sub(r"\s*@\s*", "@", t)
        norm = re.sub(r"\s+(?:at|\(at\)|\[at\])\s+", "@", norm, flags=re.I)
        norm = re.sub(r"\s+(?:dot|\(dot\)|\[dot\])\s+", ".", norm, flags=re.I)
        m = EMAIL_RE.search(norm)
        if m:
            return m.group(0).strip(".").lower()
    return None


def jar_matches(jar: dict, send_id: str) -> bool:
    sid = str(jar.get("sendId", ""))
    return sid == send_id or sid.endswith("/" + send_id)


def classify(items: list[dict], processed: set[str], since: int, min_kop: int):
    """Split statement items into (sales, unmatched) that are new."""
    sales, unmatched = [], []
    for it in items:
        tid = str(it.get("id", ""))
        if not tid or tid in processed:
            continue
        if int(it.get("time", 0)) < since:
            continue
        amount = int(it.get("amount", 0))
        if amount <= 0:  # withdrawals from the jar
            continue
        email = extract_email(it.get("comment"), it.get("description"))
        if amount >= min_kop and email:
            sales.append({"id": tid, "email": email, "amount": amount, "time": it.get("time")})
        else:
            unmatched.append({
                "id": tid,
                "amount": amount,
                "time": it.get("time"),
                "comment": it.get("comment") or "",
                "description": it.get("description") or "",
                "reason": "below price" if amount < min_kop else "no email in comment",
            })
    return sales, unmatched


def load_state() -> dict:
    if STATE_FILE.exists():
        return json.loads(STATE_FILE.read_text())
    return {"since": int(time.time()), "processed": []}


def save_state(state: dict) -> None:
    state["processed"] = state["processed"][-2000:]
    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    STATE_FILE.write_text(json.dumps(state, indent=1) + "\n")


# ---------- monobank ----------

def mono_get(path: str, token: str, retries: int = 3):
    for attempt in range(retries):
        req = urllib.request.Request(API + path, headers={"X-Token": token})
        try:
            with urllib.request.urlopen(req, timeout=30) as r:
                return json.loads(r.read())
        except urllib.error.HTTPError as e:
            if e.code == 429 and attempt < retries - 1:
                time.sleep(62)
                continue
            raise RuntimeError(f"monobank {path.split('/')[2]} HTTP {e.code}") from None


# ---------- email ----------

def build_delivery(to: str, sender: str, product: bytes) -> EmailMessage:
    msg = EmailMessage()
    msg["Subject"] = f"Your {PRODUCT_NAME} prompt pack"
    msg["From"] = f"Andrew <{sender}>"
    msg["To"] = to
    msg["Reply-To"] = sender
    text = (
        "Hi!\n\n"
        f"Thanks for buying {PRODUCT_NAME}. Your prompt pack is attached "
        f"({PRODUCT_FILENAME}).\n\n"
        "Open it in any text editor, Notion or Obsidian. Start with prompt #2 "
        "(the build spec) and #3 (CLAUDE.md) - they make every other prompt work better.\n\n"
        "Questions? Just reply to this email.\n\n"
        "Happy shipping,\nAndrew\n"
    )
    msg.set_content(text)
    msg.add_alternative(
        "<p>Hi!</p>"
        f"<p>Thanks for buying <b>{PRODUCT_NAME}</b>. Your prompt pack is attached "
        f"(<code>{PRODUCT_FILENAME}</code>).</p>"
        "<p>Open it in any text editor, Notion or Obsidian. Start with prompt #2 "
        "(the build spec) and #3 (CLAUDE.md) &mdash; they make every other prompt work better.</p>"
        "<p>Questions? Just reply to this email.</p><p>Happy shipping,<br>Andrew</p>",
        subtype="html",
    )
    msg.add_attachment(product, maintype="text", subtype="markdown", filename=PRODUCT_FILENAME)
    return msg


def build_alert(sender: str, sales: list[dict], unmatched: list[dict]) -> EmailMessage:
    msg = EmailMessage()
    total = sum(s["amount"] for s in sales) / 100
    if sales:
        msg["Subject"] = f"💰 {len(sales)} new sale(s) - {total:.0f} UAH"
    else:
        msg["Subject"] = "⚠️ Jar payment needs manual delivery"
    msg["From"] = sender
    msg["To"] = sender
    lines = []
    for s in sales:
        lines.append(f"SOLD: {s['amount']/100:.2f} UAH -> {s['email']} (pack sent automatically)")
    for u in unmatched:
        lines.append(
            f"CHECK: {u['amount']/100:.2f} UAH, {u['reason']}. "
            f"Comment: {u['comment']!r} From: {u['description']!r}. "
            "If it's a buyer, email them the pack manually."
        )
    msg.set_content("\n".join(lines) + "\n")
    return msg


def send_all(messages: list[EmailMessage], user: str, password: str) -> None:
    with smtplib.SMTP_SSL("smtp.gmail.com", 465, timeout=60) as s:
        s.login(user, password)
        for m in messages:
            s.send_message(m)


# ---------- main ----------

def main() -> int:
    if not os.environ.get("PRODUCT_B64") and os.environ.get("PRODUCT_PATH") \
            and Path(os.environ["PRODUCT_PATH"]).exists():
        os.environ["PRODUCT_B64"] = base64.b64encode(Path(os.environ["PRODUCT_PATH"]).read_bytes()).decode()
    missing = [k for k in ("MONO_TOKEN", "GMAIL_ADDRESS", "GMAIL_APP_PASSWORD", "PRODUCT_B64")
               if not os.environ.get(k)]
    if missing:
        print("Not configured yet, skipping. Missing secrets:", ", ".join(missing))
        return 0
    token = os.environ["MONO_TOKEN"]
    sender = os.environ["GMAIL_ADDRESS"]
    password = os.environ["GMAIL_APP_PASSWORD"].replace(" ", "")
    product = base64.b64decode(os.environ["PRODUCT_B64"])
    send_id = os.environ.get("JAR_SEND_ID", "67pBy3mtKn")
    min_kop = int(float(os.environ.get("MIN_AMOUNT_UAH", "180")) * 100)
    dry = os.environ.get("DRY_RUN") == "1"

    if os.environ.get("SEND_TEST") == "1":
        send_all([build_delivery(sender, sender, product)], sender, password)
        print("test delivery sent to owner")
        return 0

    state = load_state()
    processed = set(state["processed"])

    info = mono_get("/personal/client-info", token)
    jars = [j for j in info.get("jars") or [] if jar_matches(j, send_id)]
    if not jars:
        print("ERROR: jar not found for this token. Is the token from the jar owner's account?")
        return 1
    jar_id = jars[0]["id"]

    time.sleep(61)  # stay inside monobank's 1 request / 60 s limit
    frm = max(state["since"], int(time.time()) - LOOKBACK_SECONDS)
    items = mono_get(f"/personal/statement/{jar_id}/{frm}", token) or []

    sales, unmatched = classify(items, processed, state["since"], min_kop)
    print(f"checked {len(items)} jar items: {len(sales)} sales, {len(unmatched)} need review")
    if not sales and not unmatched:
        return 0

    messages = [build_delivery(s["email"], sender, product) for s in sales]
    messages.append(build_alert(sender, sales, unmatched))
    if dry:
        print("DRY_RUN: would send", len(messages), "emails")
    else:
        send_all(messages, sender, password)

    state["processed"].extend([s["id"] for s in sales] + [u["id"] for u in unmatched])
    save_state(state)
    return 0


if __name__ == "__main__":
    sys.exit(main())
