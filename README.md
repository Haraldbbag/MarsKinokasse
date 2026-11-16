# MARS Kinokasse für Home Assistant

Liest den **GetRoWo-Export** der Kinokasse MARS (verkaufte Tickets je Vorstellung) und führt ihn mit dem Spielplan des Kinoservers (Kalender der Integration [ha_dcp2000](https://github.com/Haraldbbag/ha_dcp2000)) zu **einem Kalender je Saal** zusammen.

Nur lesend: Die Integration ruft den Export per HTTP ab und schickt nichts an Kasse oder Kinoserver.

## Installation
HACS → Benutzerdefiniertes Repository `https://github.com/Haraldbbag/MarsKinokasse` (Typ Integration) → herunterladen (Version `main`) → Home Assistant neu starten → Integration „MARS Kinokasse“ hinzufügen.

Einrichtung: Name, Host des MARS-Rechners, Port, `GetRoWoID`, `GetRoWoPass`. Der Zugang wird beim Speichern getestet.

Optionen: Anzahl Säle, Abrufintervall (Standard 5 Min.), Zuordnungstoleranz (± 10 Min.), Beginn des Spieltags (4:00), Aufbewahrung gelaufener Vorstellungen (183 Tage) und je Saal der Kalender des Kinoservers (Standard `calendar.kinoN_dcp2000_spielplan`).

## Zusammenführen
- Kinoserver-Termin und Kassen-Vorstellung gehören zusammen, wenn sie im gleichen Saal liegen und der **geplante Beginn** (aus der Beschreibung „Geplant: …“, sonst der Beginn) höchstens die Toleranz von der Kassen-Startzeit abweicht. Handstarts gehören zu einer Kassen-Vorstellung, wenn sie bis 45 Min. nach deren Beginn starten.
- Beide gefunden: ein Termin, Titel aus der Kasse, Zeiten vom Kinoserver (echte Zeiten), z. B. `Wild Horse Nine (OmdU) · 31 Zuschauer`.
- Nur Kinoserver (z. B. Schulvorstellung): Titel vom Kinoserver, ohne Zuschauer.
- Nur Kasse (z. B. Veranstaltung): Titel mit `** ` vorne, Zeiten aus der Kasse.

Beide Quellen sind unabhängig: Ohne Kasse zeigt der Kalender die Kinoserver-Termine (Zuschauer mit letztem Stand), ohne Kinoserver-Kalender nur die Kassen-Termine. Die Kassen-Daten werden im HA-Speicher gehalten; gelaufene Vorstellungen bleiben erhalten, abgesagte künftige verschwinden.

## Entitäten (Beispiel Saal 1)
| Entität | Inhalt |
|---|---|
| `calendar.kino1_spielplan` | zusammengeführter Spielplan |
| `sensor.kino1_spielplan_zuschauer_nachste_vorstellung` | verkaufte Tickets der nächsten Vorstellung (Attribute: Titel, Beginn, frei, Plätze, Quelle) |
| `sensor.kino1_spielplan_zuschauer_laufende_vorstellung` | Tickets der laufenden Vorstellung |
| `sensor.kino1_spielplan_beginn_nachste_vorstellung` | Zeitstempel |
| `sensor.kino1_spielplan_beginn_erste_vorstellung`, `_beginn_letzte_vorstellung`, `_ende_letzte_vorstellung` | Spieltag (bis 4:00) |
| `sensor.kino1_spielplan_vorstellungen_heute` | Anzahl, Attribut `liste` |
| `binary_sensor.<name>_kasse_erreichbar`, `sensor.<name>_letzter_abruf` | Diagnose |

## Tests
```
python3 tests/test_logic.py                 # Logik, ohne Home Assistant
pytest tests                                 # mit pytest-homeassistant-custom-component
```
