# Ciach

Jednoplikowy trimmer MP4/MP3 dla Windows 11. Bez instalacji: uruchom `Ciach.exe`,
wrzuć plik, ustaw suwaki, wciśnij Enter. Wynik ląduje obok exe jako `<nazwa>_ciach.<ext>`.
Słownik pojęć (Fragment, Suwak, Ciach, Mały Ciach) jest w `CONTEXT.md`.

## Sterowanie

- przeciągnij MP4 lub MP3 do okna (albo na ikonę exe)
- klik w timeline: ustaw pozycję odtwarzania
- spacja: play / pauza (odtwarzanie zapętla się między suwakami)
- złap suwak i przeciągnij: zakres do wycięcia (film pokazuje klatkę pod suwakiem)
- ←/→: jedna klatka (zaznaczony suwak albo playhead), z Shift: 1 s, przytrzymanie przyspiesza
- Esc: odznacz suwak
- Home / End: początek / koniec (zaznaczony suwak albo playhead)
- kółko nad timeline'em: przybliżenie, Shift+kółko: przesuwanie, dwuklik: cały plik
- Enter: ciach (pełna jakość)
- Ctrl+Enter: mały ciach, czyli plik do 25 MB (limit Messengera). Krótkie klipy zachowują
  jakość ciachu, dłuższe schodzą z fps (60→30) i rozdzielczością (720→540→360p). Wynik
  `<nazwa>_ciach_maly.<ext>`; jeśli po trzech próbach nadal za duży, plik zostaje z komunikatem `Za duży`.

Plik źródłowy nigdy nie jest zmieniany. Postęp eksportu widać w rogu okna i w pasku tytułu.
Zamknięcie okna w trakcie eksportu przerywa go i usuwa niedokończony plik.

## Dobrze wiedzieć

- Pierwsze uruchomienie: Windows SmartScreen może ostrzec, bo exe nie jest podpisany
  („Więcej informacji” → „Uruchom mimo to”). Start trwa 3–4 s, bo exe rozpakowuje się do folderu tymczasowego.
- Karta NVIDIA ze sterownikiem 610 lub nowszym przyspiesza zwykły ciach (NVENC). Starszy
  sterownik albo brak NVIDII: kodowanie na CPU, ten sam wynik, wolniej. Mały ciach zawsze liczy na CPU.
- Gdy eksport się nie uda, obok exe pojawia się `Ciach_error.log` z pełnym poleceniem ffmpeg i jego błędem.
- Obsługiwane są MP4 z H.264 (np. z OBS, NVIDIA App, telefonu z wyłączonym HEVC). MP4 w HEVC
  nie odtworzy się w podglądzie.

## Budowanie

Wymaga Pythona 3.12+ i ffmpeg w PATH (`winget install Gyan.FFmpeg`).

```
powershell -ExecutionPolicy Bypass -File .\build.ps1
```

Uruchomienie bez budowania: `venv\Scripts\python ciach.py`.

## Tryb testowy

Ustawienie zmiennej `CIACH_DEBUG=1` włącza endpoint `POST /debug/js` na lokalnym porcie
(wykonuje JS w oknie), a `CIACH_PORTFILE=<ścieżka>` zapisuje numer portu do pliku.
Służy wyłącznie do automatycznych testów UI (`tests/drive_ui.py`); domyślnie wyłączone.
