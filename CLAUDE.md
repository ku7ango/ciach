# Ciach

Jednoplikowy trimmer MP4/MP3 dla Windows 11, bez instalacji. Użytkownik wrzuca plik, ustawia
dwa suwaki na timeline, wciska Enter, a fragment między suwakami ląduje obok exe jako
`<nazwa>_ciach.<ext>`. Zasada projektu: **żadnych przycisków ani pasków poza timeline'em**.
Cała interakcja to mysz na timeline i klawiatura (README.md ma pełną listę skrótów).
Dwa rodzaje eksportu: **Ciach** (Enter, pełna jakość) i **Mały Ciach** (Ctrl+Enter, plik do 25 MB).
Terminy domenowe są w `CONTEXT.md`; używaj ich w komunikatach, nazwach i kodzie.

## Stack i struktura

- `ciach.py` – cały backend: pywebview (WebView2) tworzy okno, wbudowany serwer HTTP serwuje UI,
  media z obsługą Range i dane binarne (`/api/wave`, `/api/frames`), ffprobe/ffmpeg robią
  analizę i eksport. Klasa `App` trzyma stan, `Api` to metody widoczne z JS. Plan jakości
  Małego Ciachu to czysta funkcja `plan_small_video` (test: `tests/test_plan_small.py`).
- `ui/app.js` – cały frontend: stan `S`, timeline na canvasie (`draw`), suwaki jako indeksy
  klatek (`frameTs` / `frameIndex`), klawiatura, pętla odtwarzania (`tick`), zdarzenia z Pythona
  przez `window.ciachEvent`.
- `build.ps1` – venv, zależności, kopia ffmpeg/ffprobe z PATH, ikona, PyInstaller `--onefile`,
  wynik `Ciach.exe` w katalogu projektu (~200 MB, w środku pełny ffmpeg).
- Python 3.14 + numpy (waveform), pywebview 6, PyInstaller 6. Brak .NET, Rusta i kompilatora C
  na maszynie deweloperskiej; nie proponuj stacków, które ich wymagają.

## Jak pracować

- Uruchomienie ze źródła: `venv\Scripts\python ciach.py [plik]`. Przebudowa: `build.ps1`.
- Test end-to-end (źródło lub exe) opisany w `agent_docs/testing.md`. Nigdy nie steruj oknem
  przez SendKeys ani nie zabieraj fokusu; używaj endpointu debugowego z tego dokumentu.
- Zanim zmienisz polecenia ffmpeg, przeczytaj `agent_docs/export_pipeline.md`: zawiera powody
  dwustopniowego seeka, semantykę zakresu klatek, drabinkę Małego Ciachu i pułapki, w które
  już raz wpadliśmy.
- Pliki `.ps1` zapisuj jako UTF-8 z BOM, inaczej PowerShell 5.1 psuje polskie znaki.
- Sprawdzaj wynik eksportu ffprobe'em (liczba klatek, start_time obu strumieni), nie tylko
  obecność pliku.
- Folder projektu jest jednocześnie folderem wyjściowym aplikacji, a użytkownik używa
  `Ciach.exe` w trakcie sesji. Usuwaj tylko pliki, które sam utworzyłeś (po dokładnej nazwie,
  nigdy wzorcem `*_ciach*`), a przed przebudową sprawdź, czy `Ciach.exe` nie jest uruchomiony.

## Fakty o środowisku, których nie widać w kodzie

- Nagrania użytkownika pochodzą z OBS: H.264 720p30, jedna ścieżka AAC, stały fps.
- Na maszynie deweloperskiej NVENC nie działa (sterownik NVIDIA starszy niż wymaga ffmpeg 8.1),
  więc eksport idzie przez x264. Fallback jest zamierzony, nie usuwaj go.
