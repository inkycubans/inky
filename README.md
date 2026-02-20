# Gratis Avinstallerare

Ett gratis alternativ till Revo Uninstaller, skrivet i Python.

## Vad gör det?

- Listar alla installerade program (från Windows-registret)
- Kör programmets egna avinstallerare
- Söker automatiskt efter **kvarlämnade filer** i:
  - AppData (Roaming, Local, LocalLow)
  - ProgramData
  - Program Files / Program Files (x86)
- Söker efter **kvarlämnade registerposter**
- Låter dig välja exakt vad som ska raderas

## Krav

- Windows 10 eller 11
- Python 3.6 eller senare → [python.org/downloads](https://www.python.org/downloads/)
- Inga extra bibliotek behövs

## Starta programmet

Högerklicka på `uninstaller.py` och välj **Kör med Python**, eller öppna en terminal och skriv:

```
python uninstaller.py
```

> **Tips:** Kör som administratör för att kunna ta bort fler kvarlämnade filer och registerposter.

## Så här avinstallerar du ett program (t.ex. Grammarly)

1. Starta programmet
2. Skriv "Grammarly" i sökfältet
3. Markera programmet i listan
4. Klicka **Avinstallera valt program**
5. Bekräfta i dialogrutan
6. Programmets egna avinstallerare körs
7. Programmet söker sedan efter kvarlämningar automatiskt
8. Bocka i vad du vill ta bort och klicka **Ta bort markerade**

## Tips

- Kryssa i **Tyst avinstallation** om du vill slippa extra klicksteg (fungerar för de flesta program)
- Du kan dubbelklicka på ett program i listan som genväg
- Klicka på kolumnrubrikerna för att sortera listan
