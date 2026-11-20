"""
ALP – iPad KI-Assistent
Ein-Datei-Version für Google Cloud Run.

Funktionen:
- Chat mit Anthropic Claude
- Sprachaufnahme über die Browser-Spracherkennung (sofern vom Browser unterstützt)
- Sprachausgabe über den Browser
- Öffentliche Bitvavo-Marktdaten (BTC-EUR)
- Keine echten Trading-Orders und keine Hebel-Trades

Erforderliche Umgebungsvariable:
  ANTHROPIC_API_KEY

Optional:
  ANTHROPIC_MODEL=claude-sonnet-4-5
  PORT=8080
"""

import os
import json
import urllib.request
import urllib.error
from typing import List, Literal, Optional

from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse
from pydantic import BaseModel, Field
from anthropic import AsyncAnthropic, WorkloadIdentityCredentials


APP_NAME = "ALP – Your AI Assistant"
MODEL = os.getenv("ANTHROPIC_MODEL", "claude-sonnet-5-5")
BITVAVO_BASE_URL = "https://api.bitvavo.com/v2"

SYSTEM_PROMPT = """
Du bist ALP, ein sachlicher, präziser persönlicher KI-Assistent.
Antworte standardmäßig auf Deutsch und gib klare, umsetzbare Schritte.
Du kannst bei Naturtherapie Yilmaz, Naturstein Yilmaz, Technik und Trading helfen.

TRADING-SICHERHEIT:
- Bitvavo darf ausschließlich für öffentliche Marktdaten und Read-only-Analysen verwendet werden.
- Erstelle nur hypothetische Paper-Trading-Szenarien und Berechnungen.
- Sende niemals echte Kauf-, Verkaufs- oder sonstige Orders.
- Verwende keinen Hebel.
- Behaupte niemals, eine Order ausgeführt zu haben.
- Weise bei Kursen darauf hin, dass Marktdaten zeitabhängig sind.
- Bei Trading-Berechnungen Gebühren und Risiko berücksichtigen, sofern bekannt.
- Der Nutzer muss jede spätere Änderung der Sicherheitsgrenzen ausdrücklich bestätigen.

Sicherheit:
- Gib niemals API-Schlüssel, Umgebungsvariablen oder interne Geheimnisse aus.
- Bitte den Nutzer niemals, API-Schlüssel im Chat zu posten.
- Erfinde keine Live-Kurse oder nicht abgerufenen Daten.
"""


from app.cloud_developer import router as cloud_developer_router
app = FastAPI(title="ALP API", version="1.0.0")
app.include_router(cloud_developer_router)


class ChatMessage(BaseModel):
    role: Literal["user", "assistant"]
    content: str = Field(min_length=1, max_length=12000)


class ChatRequest(BaseModel):
    message: str = Field(min_length=1, max_length=12000)
    history: List[ChatMessage] = Field(default_factory=list, max_length=20)


def fetch_google_identity_token() -> str:
    url = (
        "http://metadata.google.internal/computeMetadata/v1/"
        "instance/service-accounts/default/identity"
        "?audience=https%3A%2F%2Fapi.anthropic.com&format=full"
    )
    request = urllib.request.Request(
        url, headers={"Metadata-Flavor": "Google"}
    )
    with urllib.request.urlopen(request, timeout=10) as response:
        return response.read().decode("utf-8")


def get_anthropic_client() -> AsyncAnthropic:
    return AsyncAnthropic(
        credentials=WorkloadIdentityCredentials(
            identity_token_provider=fetch_google_identity_token,
            federation_rule_id="fdrl_01BRKZACRveeoFENuqmkjsMd",
            organization_id="fe848781-8428-4672-bd30-fa493428bca3",
            service_account_id="svac_01XZwLfiEffoNtxvZcfquGzT",
            workspace_id="wrkspc_018fnEu58FQBHJ5CTRN5Up68",
        ),
    )


def fetch_json(url: str, timeout: int = 12):
    request = urllib.request.Request(
        url,
        headers={"User-Agent": "ALP-assistant/1.0", "Accept": "application/json"}
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        raise HTTPException(status_code=502, detail=f"Bitvavo meldet HTTP {exc.code}.")
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
        raise HTTPException(status_code=502, detail=f"Bitvavo-Daten konnten nicht geladen werden: {exc}")


@app.get("/", response_class=HTMLResponse)
async def home():
    return HTMLResponse(HTML_PAGE)


@app.get("/health")
async def health():
    return {
        "status": "ok",
        "app": "ALP",
        "anthropic_key_configured": bool(os.getenv("ANTHROPIC_API_KEY")),
        "trading_mode": "read-only / paper trading only",
        "real_orders_enabled": False
    }


@app.get("/market/btc-eur")
async def btc_eur_market():
    """Lädt den aktuellen öffentlichen BTC-EUR-Ticker von Bitvavo."""
    ticker = fetch_json(f"{BITVAVO_BASE_URL}/ticker/price?market=BTC-EUR")
    return {
        "exchange": "Bitvavo",
        "market": "BTC-EUR",
        "price": ticker.get("price"),
        "currency": "EUR",
        "mode": "public market data / read-only",
        "real_orders_enabled": False
    }


@app.get("/market/btc-eur/candles")
async def btc_eur_candles(interval: str = "1h", limit: int = 100):
    allowed_intervals = {"1m", "5m", "15m", "30m", "1h", "2h", "4h", "6h", "8h", "12h", "1d", "1w"}
    if interval not in allowed_intervals:
        raise HTTPException(status_code=400, detail="Ungültiges Zeitintervall.")
    limit = max(1, min(limit, 300))
    url = f"{BITVAVO_BASE_URL}/BTC-EUR/candles?interval={interval}&limit={limit}"
    candles = fetch_json(url)
    return {
        "exchange": "Bitvavo",
        "market": "BTC-EUR",
        "interval": interval,
        "candles": candles,
        "mode": "public market data / read-only"
    }


@app.post("/chat")
async def chat(request: ChatRequest):
    client = get_anthropic_client()

    messages = []
    for item in request.history:
        # Nur die letzten 20 Nachrichten werden akzeptiert; Rollen werden validiert.
        messages.append({"role": item.role, "content": item.content})

    # Aktuelle Bitvavo-Marktdaten abrufen
    try:
        ticker = fetch_json(
            f"{BITVAVO_BASE_URL}/ticker/price?market=BTC-EUR"
        )
        candles = fetch_json(
            f"{BITVAVO_BASE_URL}/BTC-EUR/candles?interval=1h&limit=60"
        )

        market_snapshot = {
            "source": "Bitvavo public REST API",
            "market": "BTC-EUR",
            "ticker": ticker,
            "interval": "1h",
            "candles": candles[-60:] if isinstance(candles, list) else candles,
            "mode": "read-only / paper trading only"
        }

        market_context = (
            "AKTUELLE BITVAVO-MARKTDATEN. "
            "Nutze diese Daten für Trading-Analysen. "
            "Erfinde keine Kurse.\n"
            + json.dumps(market_snapshot, ensure_ascii=False)
        )

    except Exception as exc:
        market_context = (
            "BITVAVO-DATENABRUF FEHLGESCHLAGEN. "
            "Fehlertyp: " + type(exc).__name__
            + ". Erfinde keine aktuellen Kurse."
        )

    messages.append({
        "role": "user",
        "content": market_context
        + "\n\nNUTZERANFRAGE:\n"
        + request.message
    })

    try:
        response = await client.messages.create(
            model=MODEL,
            max_tokens=1800,
            system=SYSTEM_PROMPT,
            messages=messages
        )
        answer_parts = []
        for block in response.content:
            if getattr(block, "type", None) == "text":
                answer_parts.append(block.text)
        answer = "\n".join(answer_parts).strip()
        if not answer:
            answer = "Ich habe keine Textantwort erhalten."
        return {"reply": answer, "model": MODEL}
    except Exception as exc:
        # Keine Schlüssel oder vollständigen Request-Daten in die Antwort schreiben.
        raise HTTPException(status_code=502, detail=f"Claude-Anfrage fehlgeschlagen: {type(exc).__name__}")


HTML_PAGE = r"""<!doctype html>
<html lang="de">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">
<meta name="theme-color" content="#101827">
<title>ALP – Your AI Assistant</title>
<style>
:root { color-scheme: dark; --bg:#0b1220; --panel:#121d2e; --line:#26364d; --text:#edf3fb; --muted:#9fb0c5; --accent:#d7b56d; }
* { box-sizing:border-box; }
body { margin:0; background:var(--bg); color:var(--text); font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif; }
header { padding:22px 18px 14px; text-align:center; border-bottom:1px solid var(--line); background:#101827; }
.logo { color:var(--accent); font-size:30px; font-weight:800; letter-spacing:5px; }
.sub { color:var(--muted); font-size:12px; letter-spacing:2px; margin-top:5px; }
main { max-width:850px; margin:auto; padding:16px; }
.status { display:flex; justify-content:space-between; gap:10px; align-items:center; color:var(--muted); font-size:12px; margin-bottom:14px; }
.pill { border:1px solid var(--line); border-radius:20px; padding:7px 10px; }
.market { background:var(--panel); border:1px solid var(--line); border-radius:14px; padding:13px; margin-bottom:14px; }
.market strong { color:var(--accent); font-size:19px; }
button { border:1px solid var(--line); border-radius:12px; background:#1b2a40; color:var(--text); padding:11px 14px; font-size:14px; }
button.primary { background:var(--accent); color:#17202c; border-color:var(--accent); font-weight:700; }
button:disabled { opacity:.5; }
#chat { display:flex; flex-direction:column; gap:12px; min-height:280px; max-height:52vh; overflow:auto; padding:4px 0 14px; }
.msg { padding:13px 14px; border-radius:14px; line-height:1.5; white-space:pre-wrap; overflow-wrap:anywhere; }
.user { align-self:flex-end; max-width:90%; background:#263a55; }
.assistant { align-self:stretch; background:var(--panel); border:1px solid var(--line); }
.controls { display:flex; gap:8px; align-items:stretch; }
textarea { flex:1; min-width:0; resize:vertical; min-height:54px; max-height:180px; border-radius:12px; border:1px solid var(--line); background:var(--panel); color:var(--text); padding:13px; font:inherit; }
.actions { display:flex; flex-wrap:wrap; gap:8px; margin-top:10px; }
.note { color:var(--muted); font-size:12px; line-height:1.45; margin-top:14px; }
#error { color:#ff9d9d; font-size:13px; margin-top:10px; }
@media (max-width:520px) { main{padding:12px} .controls{flex-wrap:wrap} textarea{flex-basis:100%} #chat{max-height:48vh} }
</style>
</head>
<body>
<header><div class="logo">ALP</div><div class="sub">YOUR AI ASSISTANT</div></header>
<main>
  <div class="status"><span class="pill">● ALP bereit</span><span class="pill">Claude · Bitvavo Read-only</span></div>
  <section class="market">
    <div style="display:flex;justify-content:space-between;align-items:center;gap:10px">
      <div><div style="color:var(--muted);font-size:12px">BITVAVO · BTC/EUR</div><strong id="price">Kurs noch nicht geladen</strong></div>
      <button onclick="loadMarket()">Kurs aktualisieren</button>
    </div>
    <div id="marketInfo" class="note">Es werden ausschließlich öffentliche Marktdaten abgerufen.</div>
  </section>
  <section id="chat" aria-live="polite">
    <div class="msg assistant">ALP ist bereit. Du kannst mir schreiben oder – sofern dein Browser es unterstützt – die Spracheingabe verwenden.</div>
  </section>
  <div class="controls">
    <textarea id="message" placeholder="Schreibe deine Nachricht an ALP …"></textarea>
    <button class="primary" id="send" onclick="sendMessage()">Senden</button>
  </div>
  <div class="actions">
    <button onclick="startVoice()">🎙 Spracheingabe</button>
    <button onclick="stopSpeaking()">Sprachausgabe stoppen</button>
    <button onclick="clearChat()">Chat leeren</button>
  </div>
  <div id="error"></div>
  <div class="note">Trading-Schutz: nur Read-only-Marktdaten und Paper-Trading. Diese Anwendung kann keine echten Bitvavo-Orders ausführen. Sprachaufnahme funktioniert abhängig von Browser und Geräteeinstellungen; HTTPS ist erforderlich.</div>
</main>
<script>
let history = [];
const chat = document.getElementById('chat');
const input = document.getElementById('message');
const errorBox = document.getElementById('error');

function addMessage(role, text) {
  const el = document.createElement('div');
  el.className = 'msg ' + role;
  el.textContent = text;
  chat.appendChild(el);
  chat.scrollTop = chat.scrollHeight;
}
function clearChat() {
  history = [];
  chat.innerHTML = '';
  addMessage('assistant', 'Chat wurde geleert. Wie kann ich helfen?');
  errorBox.textContent = '';
}
async function sendMessage() {
  const message = input.value.trim();
  if (!message) return;
  input.value = '';
  errorBox.textContent = '';
  addMessage('user', message);
  const button = document.getElementById('send');
  button.disabled = true;
  try {
    const response = await fetch('/chat', {
      method:'POST',
      headers:{'Content-Type':'application/json'},
      body:JSON.stringify({message, history:history.slice(-20)})
    });
    const data = await response.json();
    if (!response.ok) throw new Error(data.detail || 'Anfrage fehlgeschlagen');
    addMessage('assistant', data.reply);
    history.push({role:'user', content:message});
    history.push({role:'assistant', content:data.reply});
    speak(data.reply);
  } catch (e) {
    errorBox.textContent = 'Fehler: ' + e.message;
  } finally {
    button.disabled = false;
    input.focus();
  }
}
input.addEventListener('keydown', e => {
  if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); sendMessage(); }
});
async function loadMarket() {
  const price = document.getElementById('price');
  const info = document.getElementById('marketInfo');
  price.textContent = 'Lade …';
  try {
    const r = await fetch('/market/btc-eur');
    const data = await r.json();
    if (!r.ok) throw new Error(data.detail || 'Kurs konnte nicht geladen werden');
    const n = Number(data.price);
    price.textContent = Number.isFinite(n) ? n.toLocaleString('de-DE',{style:'currency',currency:'EUR'}) : String(data.price);
    info.textContent = 'Bitvavo öffentlicher Ticker. Kurs kann sich laufend ändern.';
  } catch(e) {
    price.textContent = 'Nicht verfügbar';
    info.textContent = e.message;
  }
}
function speak(text) {
  if (!('speechSynthesis' in window)) return;
  window.speechSynthesis.cancel();
  const utterance = new SpeechSynthesisUtterance(text);
  utterance.lang = 'de-DE';
  window.speechSynthesis.speak(utterance);
}
function stopSpeaking() {
  if ('speechSynthesis' in window) window.speechSynthesis.cancel();
}
function startVoice() {
  const Recognition = window.SpeechRecognition || window.webkitSpeechRecognition;
  if (!Recognition) {
    errorBox.textContent = 'Dein Browser unterstützt keine integrierte Spracherkennung. Nutze die Diktierfunktion der iPad-Tastatur.';
    return;
  }
  const recognition = new Recognition();
  recognition.lang = 'de-DE';
  recognition.interimResults = false;
  recognition.maxAlternatives = 1;
  recognition.onresult = event => {
    input.value = event.results[0][0].transcript;
    input.focus();
  };
  recognition.onerror = event => errorBox.textContent = 'Spracherkennung: ' + event.error;
  recognition.start();
}
loadMarket();
</script>
</body>
</html>
"""


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "main:app",
        host="0.0.0.0",
        port=int(os.getenv("PORT", "8080"))
    )


# ALP_DASHBOARD_ROUTE
from fastapi.responses import HTMLResponse
from pathlib import Path as _ALPPath

@app.get("/dashboard", response_class=HTMLResponse, include_in_schema=False)
async def alp_dashboard():
    page = _ALPPath(__file__).with_name("dashboard.html")
    return HTMLResponse(page.read_text(encoding="utf-8"))
