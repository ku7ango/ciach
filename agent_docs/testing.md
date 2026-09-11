# Testowanie Ciach

## Zasada nadrzędna

Nigdy nie steruj oknem przez SendKeys, AppActivate ani SetForegroundWindow. Na tej maszynie
klawisze trafiły kiedyś do przeglądarki użytkownika zamiast do aplikacji. Zrzuty robimy przez
PrintWindow (działa też dla okna zasłoniętego), a UI sterujemy z wnętrza aplikacji.

Druga zasada: skrypty sprzątają tylko pliki wyjściowe własnych plików testowych (`TEST_STEMS`
w `tests/drive_ui.py`). Folder projektu to folder wyjściowy aplikacji i użytkownik trzyma w nim
swoje eksporty; wzorzec `*_ciach*` skasował je raz.

## Endpoint debugowy

`CIACH_DEBUG=1` włącza `POST /debug/js` na porcie serwera (kod w `ciach.py`, metoda `do_POST`
w `make_handler`). Body = JS, odpowiedź = wynik `evaluate_js` jako JSON. `CIACH_PORTFILE=<ścieżka>`
zapisuje numer portu do pliku, bo exe bez konsoli nie ma stdout.

W stronie `window.__ciach = { S, frameTs, frameIndex, video }` daje wgląd w stan timeline'u.
Klawisze i mysz symulujemy przez `dispatchEvent(new KeyboardEvent(...))` / `PointerEvent` /
`WheelEvent` na `window` lub na `#tl`.

## Test end-to-end

```
venv\Scripts\python tests\drive_ui.py          # źródło
venv\Scripts\python tests\drive_ui.py --exe    # zbudowany Ciach.exe
```

Ustaw `CIACH_TEST_MP4` na prawdziwe nagranie z OBS (H.264 720p30, ~55 s), inaczej skrypt
generuje syntetyczny plik. Test sprawdza: wczytanie, play/pauza, przeciąganie suwaków,
blokadę zderzenia, strzałki i Shift+strzałki, pętlę, zoom, eksport mp4 (liczba klatek = zakres),
mp3 (tagi), odrzucenie złego rozszerzenia, nazwę z `(2)`, sprzątanie po zamknięciu w trakcie eksportu.
Zrzuty lądują w `tests/` jako `t*.png`; obejrzyj je, bo asercje nie oceniają wyglądu.

## Test samego backendu

Można importować `ciach`, podstawić obiekt z metodami `run_js` i `set_title` jako `app.window`,
wywołać `app.load(path)` i `app.start_export(...)`; zdarzenia do JS trafiają do `run_js`.
Wynik eksportu weryfikuj przez `ffprobe -show_entries stream=nb_frames,start_time`.

## Testy Sekwencji i Podkładów

- `venv\Scripts\python tests\test_sekwencja.py`: backend bez okna (atrapa `window` zbiera zdarzenia
  z `run_js`). Sprawdza odrzucenie niezgodnych parametrów, sklejenie (liczba klatek, Styki, tytuł
  `+1`, plik tymczasowy), Podkład z miksem w Ciachu i Małym Ciachu (jedna ścieżka AAC, ton
  słyszalny tylko w oknie Podkładu, cisza poza nim), usunięcie Nagrania, sprzątanie temp.
  Uruchamiany też w CI (`release.yml`). Pliki testowe `tests/_seq_*.mp4`, `tests/_podklad.mp3`.
- `venv\Scripts\python tests\drive_seq.py [--exe]`: UI przez `/debug/js`. Dropy symuluje
  `window.__ciach.dropFiles(paths, x, y)`, czyli ten sam router, do którego Python oddaje
  prawdziwe upuszczenie (zdarzenie `dropped`). Pokrywa Gniazda podczas przeciągania (zrzut
  `s1_gniazda.png`), sklejenie i wstawienie na początek (Podkład jedzie z obrazem), przesuwanie
  Podkładu z Ctrl i Przyciąganie do Styku, Krawędzie, strzałki, Głośność, odtwarzanie Podkładu,
  Ciach z miksem, Delete Podkładu i Nagrania, podmianę sesji. Zrzuty `tests/s*.png`.

Oba skrypty UI (`drive_ui.py`, `drive_seq.py`) robią zrzuty i zamykają okno **po PID procesu, który
same uruchomiły** (`shot_window.ps1 -ProcId`, `close_app()`), nigdy po tytule „Ciach*”: użytkownik
zwykle ma w tym czasie otwarte własne okno `Ciach.exe`.

`window.__ciach` daje dodatkowo `dropFiles`, `layout(withStrip)`, `extent()`, `podByGen(gen)`;
`S.parts`, `S.pods`, `S.gain`, `S.sel` (null | 'left' | 'right' | {pod, edge}).
