# Shift – overdrachtsdocument

Dit document geeft een nieuwe Claude (of ontwikkelaar) alles wat nodig is om direct verder te werken aan Shift.
Laatst bijgewerkt: 18 november 2026, na het uitbrengen van versie **1.4.0**.

---

## 1. Wat is Shift

Shift is een gratis, open-source Windows-app die bestanden **lokaal** omzet, zonder iets te uploaden:
afbeeldingen, PDF, Word/Excel/PowerPoint, PDF-tekeningen naar DXF/DWG, video en audio.

- **Repository:** https://github.com/Ambulant-biv/Shift (openbaar)
- **Website (GitHub Pages, live):** https://ambulant-biv.github.io/Shift/
- **winget-ID (nog indienen):** `AmbulantBiv.Shift`
- **Taal van de app:** Engels als basis, met Nederlands en Duits; volgt de taal van Windows.
- **Shift staat volledig los van Zwanenburg.** Gebruik geen Zwanenburg-naam, -logo of -huisstijl.

### Over de gebruiker
- Spreekt Nederlands; antwoord in het Nederlands. De app en de website zijn internationaal (Engels).
- Is geen ontwikkelaar. Werkt via de **GitHub-website** (bestanden slepen, releases maken), niet via git.
- Wil **niet** dat gebruikers naast Shift nog andere software moeten installeren.
- Schermafbeeldingen sturen werkt goed om samen problemen op te lossen.

---

## 2. Huidige status

| Versie | Inhoud | Status |
|---|---|---|
| 1.1.0 | Grote uitbreiding: instellingen onthouden, volgorde bij samenvoegen, afbeeldingen verkleinen, PDF-gereedschap, talen, licht thema, automatische updates | Uitgebracht |
| 1.1.1 / 1.2.0 | Fix vastlopen bij themawissel; PDF → DXF/DWG (toen nog via ODA) | Uitgebracht (1.2.0) |
| 1.2.1 | Fix "Failed to load Python DLL" na update | Uitgebracht |
| 1.3.0 | DWG via meegeleverde LibreDWG (ODA verwijderd) | Nooit los uitgebracht; zit in 1.4.0 |
| **1.4.0** | **Installer (Inno Setup), updates via installer, winget-bestanden, website** | **Uitgebracht en op de laptop geïnstalleerd** |

### Wat er voor 1.4.0 is gedaan
- Alle bestanden staan op GitHub, inclusief `release.yml` met de stappen voor LibreDWG en de installer.
- `LICENSE` (AGPL-3.0) is toegevoegd.
- Release `v1.4.0` heeft vier assets: `Shift.exe`, `ShiftSetup.exe` en van beide een `.sha256`. Het bouwen op GitHub werkte.
- `ShiftSetup.exe` is op de laptop geïnstalleerd; Shift 1.4.0 staat bij Instellingen → Apps.
- GitHub Pages staat aan (`main` → `/docs`).

### Nog open
1. **winget** eenmalig indienen met `winget\submit-first-version.ps1 -Version 1.4.0` (Windows-PowerShell, map `winget`).
   Na acceptatie door Microsoft: klassieke GitHub-token met `public_repo` als secret `WINGET_TOKEN` toevoegen.
   Tot die tijd werkt `winget install AmbulantBiv.Shift` (dat al op de website staat) nog niet.
2. **DWG-test:** de gebruiker heeft de test-DWG's nog niet in een CAD-programma of DWG TrueView geopend. Vraag ernaar.
3. **Downloadgrootte:** `Shift.exe` is ±212 MB. Grootste winst waarschijnlijk door `pdf2docx` (trekt OpenCV mee) te schrappen,
   want PDF → Word loopt al via Microsoft Word; daarnaast ongebruikte onderdelen uitsluiten in `shift.spec`.
4. De eerstvolgende update (1.4.0 → 1.4.1) is de eerste **stille update via de installer**. Controleer met de gebruiker of die goed gaat.

### Nog niet getest (kon niet in de testomgeving)
- De stille update via de installer (pas te testen bij de volgende versie).
- Of DWG-bestanden van LibreDWG goed openen in AutoCAD/BricsCAD/DWG TrueView. **Vraag de gebruiker hiernaar.**
- Omzettingen via Microsoft Office (COM).

---

## 3. Projectopbouw

| Bestand | Doel |
|---|---|
| `shift.py` | Hoofdvenster (CustomTkinter), instellingenvenster, update-banner |
| `engine.py` | Alle omzettingen en PDF-gereedschap; geen UI-code. Fouten als `ShiftError(key)` met vertaalsleutel |
| `i18n.py` + `lang/en.json`, `nl.json`, `de.json` | Vertalingen; Engels is de terugval. Extra talen kunnen ook in `%APPDATA%\Shift\lang` |
| `settings.py` | Onthouden keuzes in `%APPDATA%\Shift\settings.json` |
| `updater.py` | Update-check via GitHub Releases, download + SHA-256-controle, herstart. `GITHUB_REPO = "Ambulant-biv/Shift"` |
| `paths.py` | Paden voor meegeleverde bestanden en gebruikersdata |
| `version.py` | Enige plek voor het versienummer |
| `shift.spec` | PyInstaller-recept (onefile, met assets, lang, licenses, tools) |
| `get_libredwg.ps1` | Downloadt LibreDWG 0.13.3 (win64) met vaste SHA-256 naar `tools/libredwg` |
| `installer/shift.iss` | Inno Setup-script, installatie per gebruiker zonder adminrechten |
| `winget/` | Manifest-sjablonen en indienscript voor winget |
| `docs/` | Website (één `index.html` + `img/`) voor GitHub Pages |
| `.github/workflows/release.yml` | Bouwt exe en installer bij een tag `v*`, publiceert de release, werkt winget bij |
| `build_and_install.bat` | Lokaal bouwen en installeren (alleen voor ontwikkelaars) |
| `licenses/LibreDWG-COPYING.txt` | GPL-tekst van LibreDWG |

---

## 4. Functies

- **Omzetten:** afbeeldingen (JPG, PNG, HEIC, WebP, TIFF, BMP, GIF, ICO), PDF (naar Word, JPG/PNG/TIFF, tekst, DXF, DWG),
  documenten, rekenbladen, presentaties (via Microsoft Office COM, anders LibreOffice), video en audio (FFmpeg via imageio-ffmpeg).
- **Samenvoegen** tot één PDF, in een volgorde die de gebruiker kiest (↑ ↓, Sorteer A–Z).
- **Afbeeldingen verkleinen/comprimeren:** vaste maten, eigen maat, kwaliteit, of maximale bestandsgrootte (binair zoeken naar kwaliteit, daarna verkleinen).
- **PDF-gereedschap** (alleen als alle bestanden PDF zijn): splitsen (losse pagina's, per N, bereiken), draaien, pagina's kiezen of verwijderen, comprimeren (licht/sterk).
- **PDF → DXF/DWG:** vectoren via PyMuPDF `get_drawings()` + tekst via `get_text("dict")`, geschreven met ezdxf; schaal 1:1 t/m 1:1000; lagen `PDF_LINES`, `PDF_FILLS`, `PDF_TEXT`.
- **Instellingen:** taal, thema (systeem/licht/donker), automatische updates.
- **Updates:** dagelijks; geïnstalleerde versie draait de nieuwe `ShiftSetup.exe` stil, de losse exe vervangt zichzelf.

---

## 5. Belangrijke keuzes en waarom

- **AGPL-3.0 / open source.** PyMuPDF valt onder AGPL. Shift openbaar houden is daarom de eenvoudigste route. Verkopen of gesloten maken vraagt een betaalde PyMuPDF-licentie of een andere PDF-bibliotheek.
- **DWG via LibreDWG, niet ODA.** De gebruiker wil geen extra installaties; ODA File Converter mag niet worden meegeleverd. LibreDWG (GPL-3.0) wordt mee gebouwd.
  - LibreDWG schrijft betrouwbaar alleen **DWG r2000** en alleen vanuit een **R2000-DXF**. Vanuit R2018-DXF kwam een **lege** DWG.
  - De R2000-DXF moet met `ezdxf.new("R2000", setup=True)`; zonder `setup` was de DWG ongeldig.
  - R2000 kent geen vrije kleuren: kleuren worden afgerond naar de 256 AutoCAD-standaardkleuren (`_nearest_aci`).
- **Updates via de installer** (vanaf 1.4.0), zodat "Apps verwijderen" en winget de juiste versie tonen.
- **Installatie per gebruiker** in `%LOCALAPPDATA%\Programs\Shift`: geen adminrechten nodig en de updater kan schrijven.
- **Repository moet openbaar zijn,** anders kan de updater de releases niet zien.
- **winget-ID `AmbulantBiv.Shift`:** er bestaan andere apps met de naam "Shift".
- **Website-ontwerp:** licht/donker volgens systeem, Engels + Nederlands, lettertypen Bricolage Grotesque en Atkinson Hyperlegible. Het enige opvallende element is de hero-afbeelding: één scherm diagonaal doorgesneden (zoals het logo), met een eenmalige schuifbeweging bij het laden. Een diagonaal snij-effect op de kop is bewust weggehaald: slecht leesbaar.
- **Logo:** document diagonaal in tweeën, de helften verschuiven langs de snede; verloop violet `#7C5CFF` → cyaan `#22D3EE`.

---

## 6. Valkuilen die al zijn opgelost (niet opnieuw maken)

- **Uploaden via de browser:** mappen/bestanden met een punt (`.github`, `.gitignore`) worden overgeslagen; `release.yml` altijd met de hand bewerken. Upload de **inhoud** van de map, niet de map zelf, en nooit `build/`, `dist/` of `__pycache__`. Controleer dat paden in de uploadlijst de juiste submap tonen (`/lang/...`, `/assets/...`).
- **Tags altijd met kleine v** (`v1.4.0`): de workflow luistert naar `v*` en controleert dat de tag gelijk is aan `version.py`.
- **`GITHUB_REPO` in `updater.py`** moet ingevuld blijven; een upload met een lege waarde zet updates uit.
- **Thema wisselen liep vast:** CustomTkinter verbergt en toont vensters bij een themawissel; met een modaal (`grab_set`) instellingenvenster bleef de app geblokkeerd. Opgelost met `_deactivate_windows_window_header_manipulation = True`, eigen titelbalkkleuring (`color_titlebar`, DWM-API) en geen `grab_set`.
- **"Failed to load Python DLL" na update:** de nieuwe exe erfde PyInstaller-omgevingsvariabelen (`_PYI_*`, `_MEIPASS2`, `TCL_LIBRARY`) van de oude. Opgelost met `clean_environment()` en `PYINSTALLER_RESET_ENVIRONMENT=1`.
- **Logo onzichtbaar in de exe:** PyInstaller miste `PIL.ImageTk`, `PIL._tkinter_finder`, `PIL._imagingtk`; staan nu als hiddenimports in `shift.spec`.
- **Gedraaide PDF-pagina's naar DXF:** coördinaten eerst met `page.rotation_matrix` omzetten.
- **Bestandsnamen:** "page 3" bij één pagina, "pages 1-3" bij meerdere.

---

## 7. Wensen en ideeën voor later

Door de gebruiker genoemd of voorgesteld, in volgorde van advies:

0. **Downloadgrootte verkleinen** (zie "Nog open").
1. **Rechtermuisklik-menu** in Windows ("Shift → Omzetten naar PDF").
2. **DWG/DXF → PDF/PNG** en **DWG ↔ DXF**; **lagen uit de PDF** (Optional Content Groups) overnemen; echte bogen/cirkels herkennen.
3. **Code-ondertekening** tegen de SmartScreen-waarschuwing (betaald certificaat of Microsoft-ondertekeningsdienst).
4. Voorkeuzes met één klik, bewaakte map, meerdere bestanden tegelijk omzetten.
5. OCR (scans → doorzoekbare PDF/Word), meer PDF-functies (paginanummers, watermerk, wachtwoord), EXIF verwijderen, video inkorten.

---

## 8. Werkwijze bij het ontwikkelen

- Test in de Linux-testomgeving met Xvfb (`ImageGrab` voor schermafbeeldingen), en waar mogelijk een PyInstaller-proefbuild om ontbrekende onderdelen te vinden.
- LibreDWG kan lokaal worden gebouwd uit `libredwg-0.13.3.tar.xz` (GitHub-release) met `CFLAGS="-O0 -g0 -w"` om binnen de tijdslimiet te blijven; test DWG door terug te lezen met `dwg2dxf` + ezdxf.
- Windows-specifieke delen (Office COM, Inno Setup, de update-wissel) kunnen alleen op Windows worden getest; vraag de gebruiker dan om een proefrelease en schermafbeeldingen.
- Verhoog bij elke wijziging die de gebruiker moet uitbrengen het nummer in `version.py`, en lever alleen de gewijzigde bestanden plus een volledige zip als back-up.
- Werkvolgorde voor een nieuwe versie: bestanden uploaden → (als `release.yml` verandert: met de hand bijwerken) → commit → **daarna** pas de release met tag `vX.Y.Z` maken. Een release vóór de juiste `release.yml` bouwt met oude instructies; dan release én tag verwijderen en opnieuw maken.
- GitHub-instellingen: de **repository**-instellingen zitten onder het tabblad Settings van de repository, niet onder de profielfoto (dat zijn accountinstellingen).
- Nieuwe teksten altijd in `en.json`, `nl.json` én `de.json` zetten, met dezelfde `{plaatshouders}`.
