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

W stronie `window.__ciach = { S, frameTs, frameIndex, seqOf, fileOf, ordAtS, video, ... }` daje wgląd w stan
timeline'u. `S.scanned` mówi, że skan Klatek już przyszedł (wcześniej `S.frames` to siatka z fps);
`S.frames` i `S.duration` to Klatki i długość Sekwencji (bez dziur), `S.fileDuration` to plik.
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

Skrypty UI (`drive_ui.py`, `drive_seq.py`, `drive_zoom.py`, `drive_cut.py`) robią zrzuty i zamykają
okno **po PID procesu, który same uruchomiły** (`shot_window.ps1 -ProcId`, `close_app()`), nigdy po
tytule „Ciach*”: użytkownik zwykle ma w tym czasie otwarte własne okno `Ciach.exe`.
Nie uruchamiaj `drive_seq.py` i `drive_cut.py` naraz: oba eksportują `_seq_a_ciach.mp4` i jeden
sprawdziłby plik drugiego. `drive_ui.py` przy przekierowaniu wyjścia do pliku potrzebuje
`PYTHONIOENCODING=utf-8` (drukuje „✓”).

`window.__ciach` daje dodatkowo `dropFiles`, `layout(withStrip)`, `extent()`, `podByGen(gen)`,
`podStart/podEnd/podLen`, `holesIn(a, b)`, `startCut()`, `executeCut()`, `undo()`;
`S.parts` (`{name, src, start, duration, in, out}`), `S.pieces` (`{ia, ib}` w Klatkach Sekwencji),
`S.pods` (`at`, `segs`), `S.gain`, `S.cut`, `S.undo`, `S.sel` (null | 'left' | 'right' | {pod, edge} | {zoom, part}).

## Testy Wycięć

- `venv\Scripts\python tests\test_wyciecie.py`: backend bez okna. Sprawdza `Fragment` (dziury,
  odcinki, czas Sekwencji, filtry), Ciach z dziurą (60 z 90 klatek, oba strumienie od zera, AAC),
  Podkład za dziurą (trzyma Klatkę), Podkład z odcinkami (ton|cisza|ton), Zbliżenie przez szew
  (statyczne, przejazd bez skoku, Rampa w czasie Sekwencji), Mały Ciach z dziurą, mp3 bez strat
  (i Mały), sklejanie z kawałkami (kopia raz albo zdublowana, `remap`). Uruchamiany w CI.
- `venv\Scripts\python tests\drive_cut.py [--exe]`: UI przez `/debug/js`. C w Playheadzie i
  dociąganie Krawędzi (dalej, bliżej, przed początkiem), blokady (Enter, ↑, drop, Z), Krawędź myszą
  z Ctrl i z Przyciąganiem do Styku, odtwarzanie pomijające Wycięcie, Esc, Delete (kawałki, Suwaki,
  Zbliżenie z pozycjami na brzegach, Podkład na swojej Klatce, tytuł `+2`), Ciach z dziurą (85
  klatek, AAC), Ctrl+Z, Wycięcie na Podkładzie (odcinki), Delete Nagrania jako Wycięcie (oba
  kierunki), sklejanie po Wycięciu (kopia A zdublowana, Podkład i Zbliżenie jadą z obrazem, lista
  cofnięć czyszczona). Zrzuty `tests/c*.png`.

## Testy Zbliżeń

- `venv\Scripts\python tests\test_zblizenie.py`: backend bez okna. Źródło `tests/_zoom_src.mp4`
  (lewa połowa czerwona, prawa niebieska); Kadr w niebieskiej połowie daje klatkę całą
  niebieską, a `signalstats` (UAVG per klatka) mówi co do klatki, gdzie Zbliżenie działa.
  Sprawdza plik poleceń sendcmd, Zbliżenie stojące, Rampy z przejazdem (monotoniczność), trzy
  pozycje (postój, przejazd, postój), Mały Ciach z miksem, Zbliżenie w sklejonej Sekwencji
  (`_zoom_pre.mp4` z przodu), sprzątanie temp.
  Uruchamiany w CI (`release.yml`).
- `venv\Scripts\python tests\drive_zoom.py [--exe]`: UI przez `/debug/js`. Kadry rysuje
  `PointerEvent` na nakładce `#ov` (Z trzymane przez osobne keydown/keyup), Zbliżenia na `#tl`.
  Pokrywa rysowanie (Zbliżenie na jedną Klatkę), Z + klik bez skutku, Cień poza przedziałem i
  wydłużenie przez jego złapanie, pozycję zapamiętaną rogiem na Klatce w środku przejazdu, rozcięcie
  przez Z + przeciągnięcie wewnątrz, przesuwanie z Ctrl (pozycje jadą razem), Przyciąganie Krawędzi
  do Suwaka, skrócenie kasujące pozycje, Rampę z rogu i Ctrl+strzałkami (zwykłe strzałki i End chodzą po Klatkach), Delete na Rampie, transform
  wideo w trakcie odtwarzania, Esc bez Cienia, Ciach przez Enter (wszystkie klatki niebieskie),
  Delete Zbliżenia. Zrzuty `tests/z*.png`.
  Po zmianie wysokości timeline'u (pojawił się wiersz) prostokąt obrazu `videoRect()` trzeba pobrać
  na nowo, bo podgląd się kurczy.
- Oba skrypty zamykają okno po PID w `finally`, także po nieudanej asercji. Nigdy nie zabijaj
  procesów testu wzorcem na `CommandLine`: wzorzec pasuje też do powłoki, która go wykonuje.
