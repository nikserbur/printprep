PRINT PREP 2.2 — preparing photos for print
===========================================

Installing
----------
Run PrintPrep-Setup.exe and press "Install". No admin rights are needed: the app goes into your user
folder, shortcuts appear on the desktop and in the Start menu, and Print Prep starts. Updating works
the same way: a new PrintPrep-Setup.exe → "Update"; presets are kept. To remove it: Settings → Apps →
Print Prep → Uninstall.
The installer is not code-signed, so Windows may say "Windows protected your PC": click
"More info" → "Run anyway".


In short
--------
1. Open a folder of photos ("Open folder" button, or drag the folder into the window).
2. Pick a preset on the left, for example "Photo lab 4×6 in". It applies to all photos at once.
3. Press "Prepare N photos" at the top right.

Finished files appear in a new subfolder PrintPrep_<preset>_<date> next to the originals.
Originals are never overwritten. Processing is fully local, without internet.

On first launch the app shows a short tour of the window (skip it with Esc, repeat it from
App settings).


Theme, language and app settings
--------------------------------
The sliders button at the top right opens "App settings":
  Theme       — "As in Windows", light or dark. Switches at once; folder and photo stay open.
                The surround of the photo is neutral grey in every theme, so colour is judged fairly.
  Language    — Русский or English. The app restarts quickly and reopens the same folder.
  Animations  — splash and loading animations; turn them off on a very slow computer.
  "Show the tour again" — repeat the tour.


The window
----------
Left    — the preset list: "Basics", "Print", "Screen and web", "Neural network" and your "Mine".
Middle  — live preview of the selected photo, with a filmstrip of the whole folder below it.
Right   — the preset card, histogram and settings. The switch:
          "All photos" — preset settings for the whole folder;
          "This photo" — edits of the selected photo only, on top of the preset.
Bottom  — status bar: file, preview time, neural network progress.

Every change is visible in the preview immediately. There is no "Apply" button.
Ctrl+Z undoes, Ctrl+Y redoes.

Above the preview:
  Result / Before / after / Original
                       — view mode. "Before / after" shows the original on the left and the result
                         on the right; drag the divider with the mouse. Key \ toggles it.
  Fit / 1:1 / 2:1      — zoom. "1:1" is one file pixel per screen pixel: real sharpness, noise and
                         the neural network's work are visible there. Double-click the photo for 1:1
                         at that point; Ctrl+wheel zooms.
  Crop (C)             — crop frame: drag the frame, wheel zooms, corners resize.
  Rotate (Ctrl+[ / ])  — by 90° for this photo.
  Safe zone            — a dashed line 3 mm from the edge: borderless prints may lose the edges.
  ICC proof / gamut    — appear when a printer ICC profile is selected.
  Surround             — dark, mid-grey (ISO 12646, for judging colour) or light.
In a narrow window the toolbar switches to icons; browse with the arrow keys and the filmstrip.

Chips below the preview show the final size, detail in PPI, enlargement or reduction, warnings,
"Neural ✓" or the hint "Low resolution — the neural network will help". The yellow chip at the
top lists problem photos of the batch; click it to jump to one. Filmstrip badges: pencil — the
photo has its own edits; triangle — a warning.


Presets
-------
Click a preset to apply it to the whole folder. The selected preset is outlined.
Above the settings the app always says which preset you are editing: changes on the "All photos"
tab change that preset and apply to every photo in the folder at once.
Built-in groups collapse when you click their title (the selected preset stays visible).
The preset card shows its name and parameters. Change something and a dot appears next to the
name, with "Reset" and "Save" (for a built-in preset "Save as mine…": built-in presets stay
fixed, your copy goes to "Mine").
The "Preset" button in the card holds every action: save, save as new, rename, duplicate, reset,
export and import a file, delete, manage presets. "New" above the list saves the current settings
as a new preset. "…" next to a preset (on hover) and right-click open its menu.
A preset file can be sent to colleagues; they import it. Version 1.x recipes work too.
Folder menu → "Export recipe" saves the preset together with the per-photo edits.

Per-photo edits of every folder are saved automatically and restored next time.


"All photos" settings
---------------------
Size and framing
  Original — pixels stay as they are.
  Print    — paper format (4×6 in = 102×152 mm and others), custom mm, PPI (300 for photo prints).
  Pixels   — exact size, with templates for 4K, Full HD, Instagram.
  Edge     — long edge in pixels, proportions kept.
  Fill     — fills the format, cropping the excess. Smart framing moves the frame to faces and
             the main subject.
  Fit      — the whole frame with borders; the border colour is selectable.

Light and colour
  Smart auto correction analyses every photo on its own and fixes only real faults:
    • white balance: near-neutral surfaces vote for the colour of the light; textured surfaces
      count more than smooth sky or backdrops. A real cast (wrong camera WB) shifts shadows and
      highlights alike and is corrected almost fully. Warm sunset or lamp light leaves shadows
      neutral, so that mood is kept. If there are faces, skin is never pushed green or purple;
    • exposure: brightens a dark frame, and a frame without a single bright pixel (shot darker
      than it should be). Intentionally dark frames with highlights and bright scenes (snow, white
      backgrounds) stay as they are; faces are taken into account;
    • auto levels: at full strength only when the histogram stops short at both ends (a flat,
      faded frame); pastel and matte frames get only a light touch;
    • shadows are lifted only where they hold detail: a black backdrop or night sky stays black;
    • a strong veil (fog, glare through glass, a faded print scan) is removed with a dark-channel
      dehaze; bright saturated graphics are not touched;
    • contrast, vibrance of dull photos, noise reduction from the measured noise.
  "Strength" scales all automatic edits. The chips "White balance / Light / Colour / Noise"
  turn the groups on and off; below them you see what auto did to the current photo.
  Manual sliders add to the automatic result: exposure (highlights roll off softly), contrast,
  highlights, shadows, whites, blacks, temperature, tint, vibrance (protects skin), saturation.
  Double-click a slider to reset it; click the number to type an exact value. The mouse wheel
  changes only a focused slider, so scrolling the panel is safe.

Detail and noise — clarity (local contrast), dehaze, noise reduction, colour noise.
Style            — neutral, vivid, warm, fresh, soft portrait, film, matte, B&W, B&W contrast,
                   with adjustable strength.
Neural network   — one switch "Enhance with the neural network" (Real-ESRGAN: restores detail,
                   removes JPEG artefacts and noise). The best settings are automatic; "Advanced…"
                   opens strength and the "Clean ↔ Detail" control: left removes more noise, right
                   keeps grain, grass and hair. It runs only for photos enlarged 1.3× or more
                   (photos over 4 MP already have enough detail), once per photo in the background,
                   with progress and time left in the corner of the preview. After that colour edits
                   and strength apply instantly; inspect detail at 1:1.
Print and file
  JPEG (quality 50–100, no chroma subsampling), TIFF or PNG 8/16-bit.
  Colour: sRGB (the lab standard) or a printer and paper ICC profile (RGB or CMYK).
  Sharpen for: screen / gloss / matte. The radius follows PPI; amount — low, normal, high.
  Print brightness: a print is darker than a glowing screen. Lifts the midtones without changing
  black and white. Tune it with a test print and save it in a preset for your paper.
  Keep EXIF: date and camera are kept, GPS is removed, orientation is reset.


"This photo" settings
---------------------
Crop: edit the frame, rotate, straighten (±20°). Mode "As in preset / Fill / Fit" or the aspect
ratio for the "Original" and "Edge" size modes.
Light, colour and detail: final values are shown; the mark on the scale is the preset value.
Neural network: as in preset / on / off for this photo, with its state for this photo.
"Reset" removes all edits of the photo. "To preset" moves colour edits into the preset for all.
"Copy" applies the edits to photos selected in the filmstrip (Ctrl or Shift + click).


Printing tips
-------------
• Photo labs and minilabs (Fujifilm Frontier, Noritsu) expect sRGB, JPEG and 300 PPI at the print
  size. 240 PPI is good; below 150 PPI detail gets noticeably softer.
• Choose a printer ICC profile only when your printer asks for it, and do not turn on colour
  management a second time in the printer driver.
• For borderless prints keep important things 3 mm from the edge: turn on the safe zone.
• Matte paper needs stronger output sharpening than gloss.
• Prints look darker than the screen: lower the monitor brightness (80–120 cd/m²) or use
  "Print brightness" and make a test print.
• Enlarging does not create real detail. The neural network invents plausible detail — check at 100%.


Keyboard shortcuts
------------------
←/→ photos · Space or Z fit/100% · \ before/after · C crop · Ctrl+[ ] rotate
Ctrl+Z/Ctrl+Y undo/redo · Ctrl+S save preset · Ctrl+E prepare · Ctrl+O folder · F1 help
Double-click the photo for 100% at that point. Ctrl+wheel zooms.


Formats
-------
In:  JPEG, PNG, TIFF (8/16-bit), WebP, BMP. Embedded profiles (Display P3, Adobe RGB and others) are
     converted to sRGB with soft compression of out-of-gamut colours. Photos up to 100 MP.
     RAW and HEIC are not supported: save JPEG or TIFF from your editor.
Out: JPEG, TIFF 8/16-bit (LZW or Deflate), PNG 8/16-bit. Embedded ICC profile, PPI, EXIF without GPS.
     A report.csv and report.json in the same folder list the status of each file and what was applied.


Building the Windows app
------------------------
You need Windows 10/11 x64 and Python 3.12 x64 (python.org). If py says
"No runtime installed that matches 3.12", run in PowerShell:  py install 3.12
Then double-click build_exe.bat. The script installs dependencies, runs the tests, builds the
PrintPrep folder with PrintPrep.exe, checks the self-test, creates dist\PrintPrep-Windows-x64.zip and
the installer dist\PrintPrep-Setup.exe, then checks the installer: a silent install into a temporary
folder, a self-test of the installed app, and an uninstall.
Give colleagues the single file PrintPrep-Setup.exe. The ZIP is for a portable folder without
installing (start PrintPrep.exe from the PrintPrep folder; _internal sits next to it).
The build will not start while Print Prep runs from dist\PrintPrep — close it first.
The folder build starts in 1–2 seconds even on a slow computer. No Python or admin rights needed.
The exe is not code-signed, so Windows SmartScreen may warn on first launch
("More info" → "Run anyway").

From source:
  py -3.12 -m venv .venv
  .venv\Scripts\python -m pip install -r requirements-dev.txt
  .venv\Scripts\python print_prep.py
Installation check: .venv\Scripts\python print_prep.py --self-test


Deliberately not included
-------------------------
RAW/HEIC, direct printing (risk of double colour management), skin retouching, cloud.
The working space is sRGB. Output to a printer ICC profile is 8-bit.
No quality or speed comparison with Photoshop was made: judge with test prints.
