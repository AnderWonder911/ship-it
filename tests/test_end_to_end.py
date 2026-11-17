"""Full run of main() against a fake monobank API and a fake SMTP server."""
import base64
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "delivery"))
import deliver as d  # noqa: E402


def test_full_run(tmp_path, monkeypatch):
    state = tmp_path / "processed.json"
    state.write_text(json.dumps({"since": 1_000, "processed": ["old"]}))
    monkeypatch.setattr(d, "STATE_FILE", state)
    monkeypatch.setattr(d.time, "sleep", lambda s: None)

    def fake_get(path, token, retries=3):
        assert token == "tok"
        if path == "/personal/client-info":
            return {"jars": [{"id": "OTHER", "sendId": "jar/zzz"}, {"id": "JAR1", "sendId": "jar/67pBy3mtKn"}]}
        assert path.startswith("/personal/statement/JAR1/")
        return [
            {"id": "old", "time": 2_000, "amount": 20_000, "comment": "x@x.com"},
            {"id": "t1", "time": 2_000, "amount": 20_000, "comment": "pls send to Buyer@Mail.com", "description": "Від: B"},
            {"id": "t2", "time": 2_000, "amount": 20_000, "comment": "slava ukraini", "description": "Від: C"},
        ]

    sent = []
    monkeypatch.setattr(d, "mono_get", fake_get)
    monkeypatch.setattr(d, "send_all", lambda msgs, u, p: sent.extend(msgs))
    monkeypatch.setenv("MONO_TOKEN", "tok")
    monkeypatch.setenv("GMAIL_ADDRESS", "me@gmail.com")
    monkeypatch.setenv("GMAIL_APP_PASSWORD", "abcd efgh ijkl mnop")
    monkeypatch.setenv("PRODUCT_B64", base64.b64encode(b"# pack").decode())

    assert d.main() == 0
    assert [m["To"] for m in sent] == ["buyer@mail.com", "me@gmail.com"]
    alert = sent[1].get_content()
    assert "buyer@mail.com" in alert and "no email in comment" in alert
    saved = json.loads(state.read_text())
    assert set(saved["processed"]) == {"old", "t1", "t2"}

    # second run: nothing new, nothing sent
    sent.clear()
    assert d.main() == 0
    assert sent == []


def test_unconfigured_is_noop(monkeypatch):
    for k in ("MONO_TOKEN", "GMAIL_ADDRESS", "GMAIL_APP_PASSWORD", "PRODUCT_B64"):
        monkeypatch.delenv(k, raising=False)
    assert d.main() == 0
