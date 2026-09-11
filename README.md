# <img src="assets/icon.png" width="40" valign="middle" alt=""> Ciach

Jednoplikowy trimmer MP4/MP3 dla Windows 11. Bez instalacji: uruchom `Ciach.exe`,
wrzuć plik, ustaw suwaki, wciśnij Enter. Wynik ląduje obok exe jako `<nazwa>_ciach.<ext>`.
Słownik pojęć (Fragment, Suwak, Ciach, Mały Ciach) jest w `CONTEXT.md`.

**Pobieranie:** gotowy `Ciach.exe` jest w zakładce
[Releases](https://github.com/ku7ango/ciach/releases). Nie wymaga instalacji ani Pythona. Historia zmian: `CHANGELOG.md`.

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

### Sklejanie nagrań

- przeciągnij kolejny MP4 (albo kilka naraz) na timeline: w trakcie przeciągania na początku,
  końcu i na każdym styku pojawiają się gniazda. Upuszczenie w gniazdo wstawia nagranie w to
  miejsce, upuszczenie na film podmienia całą sesję jak dotąd.
- sklejanie nie przekodowuje, więc nagrania muszą mieć tę samą rozdzielczość, kodek, format
  pikseli i takie samo audio (kodek, częstotliwość, kanały). Fps może się różnić: sklejka
  30 + 60 fps jest po prostu zmiennoklatkowa i ciach zachowuje wszystkie klatki. Kilka plików
  naraz wchodzi w kolejności nazw. Suwaki po sklejeniu obejmują całość, wynik nazywa się po
  pierwszym nagraniu.
- Delete / Backspace bez zaznaczenia: usuwa nagranie, w którym stoi playhead (rysowane
  odrobinę jaśniej). Ostatniego nagrania nie da się usunąć.
- to samo działa dla MP3 z MP3.

### Podkład (muzyka pod wideo)

- przeciągnij MP3 na pasek pod timeline'em: powstaje osobny wiersz z podkładem, który zaczyna
  się od początku filmu. Każdy kolejny MP3 dodaje kolejny wiersz. Upuszczenie MP3 na film
  nadal podmienia sesję.
- złap środek podkładu i przeciągnij: przesuwanie. Złap krawędź: przycinanie (muzyka zostaje
  na miejscu, zmienia się tylko, od kiedy i do kiedy ją słychać). Krawędzie przyciągają się
  do styków, suwaków, playheada, początku i końca filmu oraz innych podkładów; Ctrl podczas
  przeciągania wyłącza przyciąganie.
- zaznaczony podkład albo jego krawędź: ←/→ przesuwa o klatkę (Shift: 1 s), Home / End
  dosuwa do początku / końca filmu, Delete usuwa.
- ↑/↓: głośność (5 %, z Shift 1 %) zaznaczonego podkładu, a bez zaznaczenia głośność filmu.
- podkład może wystawać za koniec filmu (timeline się wtedy wydłuża); przy ciachu liczy się
  tylko fragment między suwakami. Dźwięk filmu i podkłady miksują się do jednej ścieżki AAC
  192 kbit/s; bez podkładów i przy głośności 100 % dźwięk jest kopiowany 1:1 jak dotąd.
Plik źródłowy nigdy nie jest zmieniany. Sklejone nagrania trafiają jako jeden plik tymczasowy do
folderu tymczasowego systemu i znikają po zamknięciu okna. Postęp eksportu widać w rogu okna i w pasku tytułu.
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

Wydanie nowej wersji: wypchnij tag `vX.Y.Z`, a workflow `.github/workflows/release.yml` zbuduje
exe na GitHubie i podepnie go pod release.

## Tryb testowy

Ustawienie zmiennej `CIACH_DEBUG=1` włącza endpoint `POST /debug/js` na lokalnym porcie
(wykonuje JS w oknie), a `CIACH_PORTFILE=<ścieżka>` zapisuje numer portu do pliku.
Służy wyłącznie do automatycznych testów UI (`tests/drive_ui.py`, `tests/drive_seq.py`); domyślnie wyłączone.
