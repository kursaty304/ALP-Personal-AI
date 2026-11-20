import json
import subprocess
import urllib.request
import urllib.error
from pathlib import Path

BASE = "https://alp-api-87321711624.europe-west1.run.app"

def check(name, fn):
    try:
        result = fn()
        print(f"[OK] {name}: {result}")
    except Exception as e:
        print(f"[FEHLER] {name}: {e}")

def request(path, method="GET", data=None):
    body = json.dumps(data).encode() if data else None
    req = urllib.request.Request(
        BASE + path, data=body, method=method,
        headers={"Content-Type": "application/json"}
    )
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.loads(r.read().decode())

def tests():
    r = subprocess.run(
        ["./.venv/bin/python", "-m", "unittest", "discover", "-s", "app", "-v"],
        capture_output=True, text=True, timeout=120
    )
    if r.returncode:
        raise RuntimeError((r.stdout + r.stderr)[-2500:])
    return "Tests bestanden"

def health():
    d = request("/health")
    if d.get("status") != "ok":
        raise RuntimeError(str(d))
    return "API online; Secret konfiguriert: " + str(d.get("anthropic_key_configured"))

def developer():
    d = request("/developer/status")
    return json.dumps(d, ensure_ascii=False)

def tasks():
    try:
        d = request("/developer/tasks")
        return "Aufgaben-Endpunkt erreichbar"
    except urllib.error.HTTPError as e:
        if e.code == 503:
            return "Admin-Zugang noch nicht konfiguriert (erwartet)"
        raise

def claude():
    d = request("/chat", "POST", {
        "message": "Antworte kurz: ALP-Claude-Verbindung erfolgreich."
    })
    return str(d)[:500]

print("\n=== ALP GESAMTDIAGNOSE ===")
check("Lokale Tests", tests)
check("Cloud-API und Secret", health)
check("Cloud-Developer-Status", developer)
check("Admin-Aufgaben", tasks)
check("Claude-Test", claude)
print("\n=== DIAGNOSE BEENDET ===")
print("Keine echten Orders oder Code-Ausführung aktiviert.")
