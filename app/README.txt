# ALP Trading Engine – erste lokale Version

## Inhalt
- `trading_engine.py`: Indikatoren, Candle-Validierung, Risiko-/Positionsgrößenberechnung und Paper-Trading.
- `test_trading_engine.py`: lokale Unit-Tests.

## Sicherheitsgrenzen
- Nur öffentliche Marktdaten, die der Aufrufer bereitstellt.
- Das Modul macht selbst keine Netzwerkverbindungen.
- Keine Bitvavo-Authentifizierung, keine privaten API-Endpunkte und keine Orders.
- Long-only Spot-Simulation; kein Shorting und kein Hebel.
- Standardwerte: 100 EUR Startkapital, maximal 1 EUR geplantes Risiko je Trade, 0,25 % Gebühr je Seite.
- Der Risikoansatz berücksichtigt geschätzte Ein- und Ausstiegsgebühren.
- Indikatoranalyse nutzt standardmäßig nur abgeschlossene Kerzen und benötigt 200 Bars für EMA 200.
- Paper-Trading-Zustand liegt vorerst nur im Arbeitsspeicher. Er geht bei einem Prozess-/Containerneustart verloren. Vor produktiver Nutzung muss persistente Speicherung ergänzt werden.
- Stop-/Take-Profit-Prüfung erfolgt nur, wenn `evaluate_exit()` mit einem neuen Kurs aufgerufen wird; kein Hintergrund-Monitor und kein Slippage-Modell.

## Einbau in Google Cloud Shell
Im Projektordner `~/alp`:
1. Datei `trading_engine.py` nach `app/trading_engine.py` hochladen.
2. Syntax prüfen: `python3 -m py_compile app/trading_engine.py`
3. Tests ausführen: `cd app && python3 -m unittest -v test_trading_engine.py`

Die bestehende `main.py` wird durch diese Lieferung nicht verändert. Die API-Routen und das Dashboard werden erst nach Prüfung der aktuellen Cloud-Shell-Version integriert.
