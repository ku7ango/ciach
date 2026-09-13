# Jak działa cięcie i dlaczego akurat tak

Pełne polecenia buduje `App.build_cmd` w `ciach.py`. Poniżej decyzje, których nie widać z kodu.

## Dwustopniowy seek

`-ss (start-3s)` przed `-i`, potem `-ss ~3s` i `-t` po `-i`. Jednostopniowy `-ss` przed `-i`
przy `-c:a copy` kopiował audio od klatki kluczowej sprzed cięcia i dawał ~1,7 s rozjazdu A/V.
Seek wyjściowy odrzuca pakiety przed cięciem także dla strumieni kopiowanych. Zapas 0,5 ms
(`oss = start - pre - 0.0005`) gwarantuje, że klatka o znaczniku `start` wchodzi, a `end` nie.

## Semantyka zakresu

Suwaki trzymają indeksy klatek. Lewy jest włączny, prawy wyłączny; prawy = N oznacza koniec pliku.
Znaczniki klatek pochodzą ze skanu pakietów przez ffprobe (`App.scan_frames`), więc zakres
w sekundach to dokładne pts, nie `i / fps`. Dla mp3 "klatka" = ramka mp3 (1152 próbek).

## Wideo

x264 `crf 16 medium` albo NVENC `cq 16 p6`. NVENC wykrywany raz przy starcie (`detect_encoder`);
przy błędzie eksportu następuje jednorazowy fallback na x264. Audio kopiowane 1:1, wszystkie
ścieżki (`-map 0:a?`). Bez `-avoid_negative_ts make_zero` dla mp4: z B-klatkami przesuwało
start wideo o 2 klatki. Dla mp3 zostaje (`-map 0 -c copy -map_metadata 0`).

## Postęp i anulowanie

`-progress pipe:1` daje `out_time_us`; procent liczony względem długości fragmentu. Zamknięcie
okna w trakcie: `cancel_export` zabija proces i usuwa częściowy plik. Błąd: `Ciach_error.log`
obok exe z pełnym poleceniem i stderr.

## Mały Ciach (Ctrl+Enter)

Cel: plik poniżej `SMALL_LIMIT` (25 000 000 bajtów, limit Messengera, bezpieczny w obu
interpretacjach MB/MiB). Plan liczy `plan_small_video` (czysta funkcja, testowana w
`tests/test_plan_small.py`), wykonanie robi `App.run_small_export`.

- Trzy próby z celami 98 %, 92 %, 85 % limitu; po każdej sprawdzany realny rozmiar pliku.
  Po trzeciej nieudanej plik zostaje, UI dostaje `toobig` z rozmiarem.
- Bitrate wideo = (budżet − audio) / czas, ograniczony do bitrate źródła (krótkie klipy =
  jakość zwykłego Ciachu w mniejszym pliku).
- Drabinka wg bitów na piksel na klatkę (`SMALL_BPP` = 0,05): najpierw 60→30 fps, potem
  wysokość 540, 360. Próg dobrany tak, by 720p30 trzymało pełną rozdzielczość do ~2 min.
- Audio: ≤90 s kopia 1:1 (jedna ścieżka) albo AAC 160k (miks wielu ścieżek), ≤3 min 128k,
  ≤6 min 96k, dłużej 64k mono.
- Zawsze x264 `slow` two-pass (`-pass 1` do `NUL`, `-pass 2` do pliku), niezależnie od NVENC:
  NVENC nie trzyma rozmiaru. Logi two-pass w katalogu tymczasowym sprzątanym w `finally`
  i w `cancel_export`. Filtry (`fps`, `scale`, `amix`) idą przez jeden `-filter_complex`,
  bo `-vf` i `-filter_complex` nie mogą wystąpić razem.
- H.264, nie HEVC: Messenger na desktopie wysyła plik bez przekodowania, a odbiorca na
  Windows bez płatnego rozszerzenia nie odtworzy HEVC.
- mp3: najpierw zwykła kopia; gdy za duża, libmp3lame 128 → 96 → 64 kbit/s; gdy nawet 64
  nie wystarczy, plik usuwany i UI dostaje `toolong`.

## Sekwencja (sklejanie Nagrań)

Decyzja i powody: `docs/adr/0001-sekwencja-jako-plik-tymczasowy.md`. `App.build_sequence` skleja
części przez concat demuxer (`-f concat -safe 0 -i lista.txt -map 0 -c copy`, dla mp4 z `+faststart`)
do `%TEMP%\ciach_seq_*\seq_<gen>.<ext>`, a potem ładuje wynik jak zwykłe Nagranie (`install_media`).
`Media.parts` trzyma części z czasami startu (Styki), `display_name` nazwę pierwszego Nagrania
(tytuł, nazwa wyniku). Zgodność parametrów sprawdza `Media.signature()` przed sklejeniem.

Pułapki, które już widzieliśmy:

- ffprobe liczy dla sklejki średni fps jako klatki / czas, a czas concat zaokrągla o ogon audio:
  dwa Ciachy 30 fps dają sklejkę „29,9509 fps”. Dlatego sygnatura Sekwencji to `Media.sig`
  skopiowana z pierwszego Nagrania, a fps w ogóle nie wchodzi do sygnatury.
- Sklejka 30 + 60 fps jest zmiennoklatkowa. Bez `-enc_time_base:v demux` x264 dostawał bazę
  czasu 1/30 z pierwszej części i gubił co drugą klatkę części 60 fps (59 zamiast 89 klatek).
  Flaga jest w `VIDEO_TB` i idzie do obu eksportów; `:v`, bo dla audio z filtra „demux” nie
  istnieje i ffmpeg przerywa z „Demuxing timebase not available”.

- Pliki z AAC mają na starcie opóźnienie kodera (pierwszy pakiet audio przy −23 ms). Concat
  demuxer przesuwa cały plik tak, żeby zaczynał się od zera, więc wideo i audio w sklejce są
  o te ~23 ms później niż w źródle, ale **razem**: synchronizacja A/V jest zachowana, a
  pierwsza klatka ma pts ~0,023 zamiast 0 (skan klatek to widzi, `frameTs(0)` i tak zwraca 0).
- Na Styku ffmpeg ostrzega `Non-monotonic DTS`: ogon audio poprzedniej części (padding AAC)
  nachodzi na początek następnej o ~20 ms. To cecha kopiowania AAC bez przekodowania; słyszalne
  co najwyżej jako minimalny szew, akceptowane.
- Sekwencja z jednym Nagraniem nie tworzy pliku tymczasowego: po usunięciu części do jednej
  ładowany jest oryginał.

## Zbliżenia (crop sterowany per klatka)

UI wysyła w `mix.zblizenia` listę `{at, end, rin, rout, keys: [{t, x, y, s}]}`: czasy Sekwencji
(pts Klatek, `end` wyłącznie), a `keys` to pozycje Kadru zapamiętane na Klatkach, jako ułamki obrazu
(`s` = bok Kadru względem szerokości i wysokości, więc proporcje obrazu są zachowane z definicji;
0,2 ≤ s ≤ 1). Między pozycjami Kadr jest liniowy w czasie, przed pierwszą i za ostatnią stoi
(`App.kadr_keys`); Rampa mnoży: widziany Kadr = całość + (Kadr − całość) · f, gdzie f rośnie liniowo
0→1 w Rampie wejścia i maleje w Rampie wyjścia (`App.ramp_factor`). `App.resolve_zoom` waliduje
i sortuje, `App.zoom_commands` pisze plik poleceń, `App.zoom_chain` daje łańcuch wideo:

```
[0:v:0]sendcmd=f=zoom.cmd,crop=w=iw:h=ih:x=0:y=0,scale=W:H[v]
```

Dlaczego tak, a nie prościej:

- `crop` liczy `w`/`h` tylko raz przy konfiguracji (per klatka są tylko `x`/`y`), więc Rampa
  i przejazd A→B o różnej krotności nie dadzą się zapisać wyrażeniem od `t`.
- `zoompan` przeliczałby pts od zera z własnym fps (sklejka 30 + 60 fps traciłaby klatki),
  a `scale` z `eval=frame` przed `crop` daje klatki o zmiennym rozmiarze, których `crop` nie obsłuży.
- `sendcmd` wysyła do `crop` polecenia `w h x y` (crop je obsługuje) na każdej klatce w odcinku
  z flagą `[expr]` (zmienna `TI` = 0..1 w obrębie odcinka) albo raz przy wejściu w odcinek
  (`[enter]`, stały Kadr). Wyjście `crop` ma wtedy zmienny rozmiar, a `scale` jest jedynym
  filtrem, który przy zmianie rozmiaru wejścia sam się rekonfiguruje; wynik ma stały `W:H`.
- Czas w grafie = czas Sekwencji − `pre` (wejściowy `-ss` zeruje znaczniki na punkcie seeku,
  `scan_frames` odejmuje `start_time`, więc obie strony liczą to samo; sprawdzone na nagraniu
  OBS przez `showinfo`). Odcinki dostają ten sam zapas 0,5 ms co cięcie (`ZOOM_EPS`).
- Plik poleceń leży w katalogu tymczasowym eksportu, a ffmpeg dostaje ten katalog jako `cwd`:
  ścieżka względna `zoom.cmd` omija escapowanie `C:\` i spacji w składni filtergraph.
- Odcinki: punkty podziału to `at`, `end`, końce Ramp i czasy pozycji. W odcinku Kadr i f są liniowe
  w TI, więc ich iloczyn jest kwadratowy: `c0+c1*TI+c2*TI*TI`, współczynniki z trzech punktów
  (TI = 0, ½, 1). Odcinek bez ruchu to `[enter]` ze stałymi wartościami. W wyrażeniach nie ma
  przecinków (przecinek rozdziela polecenia sendcmd), stąd żadnych `if`/`max`. Odcinki po ostatnim
  Zbliżeniu i między Zbliżeniami resetują crop do całości.
- Mały Ciach: łańcuch Zbliżenia skaluje od razu do rozmiaru z planu (`scale=ow:oh` z parzystą
  szerokością), bo `-2:h` liczyłoby szerokość osobno dla każdej klatki o innym rozmiarze.
  Idzie do obu przebiegów two-pass. `crop` z `exact=0` sam wyrównuje w/h/x/y do parzystych.

## Wycięcia (dziury w Fragmencie)

Decyzja i powody: `docs/adr/0002-wyciecie-wirtualne.md`. Plik tymczasowy Sekwencji zostaje sklejką
całych plików (`Media.copies`), a Nagrania to kawałki kopii (`Media.parts`: `{src, in, out}` w sekundach
pliku źródłowego); to, czego nie ma w `parts`, jest dziurą. UI po każdym Wycięciu, usunięciu Nagrania
i Cofnięciu przysyła nowy skład przez `Api.set_parts`, a przy Ciachu dodatkowo listę dziur wewnątrz
Fragmentu (`holes`, w czasie pliku). `Fragment(start, end, holes)` trzyma zakres, dziury, `pre`,
odcinki (`segments`) i przelicznik czasu pliku na czas Sekwencji (`seq`) i grafu (`graph`).

- **Obraz**: za łańcuchem Zbliżenia (jeśli jest) idą `select='between(t,a,b)+...'` (tylko klatki
  z zachowanych odcinków, z tym samym zapasem 0,5 ms co cięcie) i `setpts='PTS-(gte(T,h)*d+...)/TB'`
  (każda klatka za dziurą dosunięta o jej długość, żeby znaczniki były ciągłe; bez tego vfr
  zostawiłby zamrożony obraz). Baza czasu `demux` zostaje, klatki nie giną (`nb_frames` =
  zachowane). sendcmd stoi **przed** `select`, więc czasy w pliku poleceń są nadal czasem pliku
  minus `pre`; tylko wartości Kadru między pozycjami i Rampy liczą się w czasie Sekwencji
  (`kadr_keys`/`ramp_factor` z `seq`), a granice dziur i końce Ramp są punktami podziału odcinków.
- **Dźwięk**: kopia 1:1 nie umie pominąć dziury, więc Fragment z dziurą zawsze idzie torem miksu
  (`mix = {gain 1, bez Podkładów}`, jedna ścieżka AAC 192k). W `mix_filters` dźwięk Sekwencji to
  `asplit` → `atrim` per odcinek → `concat`; pierwszy odcinek zaczyna się w `pre` (graf 0), żeby
  wyjściowy `-ss` ciął dźwięk i obraz w tym samym miejscu. Podkład dostaje `adelay` z `graph(at)`
  (czas Sekwencji minus `pre`), więc gra ciągle przez szew; jego własne odcinki (`segs`, po Wycięciach
  na Podkładzie) to też `atrim` + `concat`. `-t` = długość bez dziur.
- **mp3**: filtrów nie ma (kopia), więc `cut_mp3` najpierw kopiuje każdy odcinek osobno (ten sam
  dwustopniowy seek, ramka mp3 = Klatka) do katalogu tymczasowego, skleja concat demuxerem z tagami
  z oryginału (`-i oryginał -map_metadata 1`) i dopiero na tym pliku działa zwykły tor mp3
  (Ciach i Mały Ciach, zakres 0..długość). Na szwie możliwy minimalny trzask z rezerwuaru bitów.
- Sklejanie po Wycięciu (`App.join`): sąsiednie kawałki tej samej kopii idą do listy concat raz,
  wstawienie między dwa kawałki jednej kopii dubluje plik w sklejce. `join done` niesie `remap`
  (`[[stary początek, stary koniec, przesunięcie], ...]` per dawne Nagranie), którym UI przesuwa
  Podkłady, Zbliżenia i Playhead, dosuwając je do najbliższej Klatki (pierwsza Klatka sklejki leży
  ~0,02 s od zera przez opóźnienie AAC, „ostatnia Klatka ≤ t” myliłaby się o jedną).

Test: `tests/test_wyciecie.py` (dziury w obrazie i dźwięku, Zbliżenie przez szew, odcinki Podkładu, mp3,
sklejanie z kawałkami).

Test: `tests/test_zblizenie.py` mierzy `signalstats` (UAVG) per klatka na źródle
czerwony | niebieski: Kadr w niebieskiej połowie daje klatkę całą niebieską, więc granice
Zbliżenia, Rampy, przejazd między pozycjami i sklejka są sprawdzane co do klatki.

## Podkłady i Głośność (miks)

`App.resolve_mix` zwraca `None`, gdy nic nie ma do miksowania (brak Podkładów, Głośność 100 %):
wtedy polecenia są identyczne jak dawniej (`-c:a copy`). W przeciwnym razie `App.mix_filters`
buduje jeden graf:

- dźwięk Sekwencji: `[0:a:0]…[0:a:n]amix=normalize=0,volume=<Głośność>` (wszystkie ścieżki OBS
  do jednej),
- każdy Podkład jako kolejne wejście `-i` (po wejściu 0, przed wyjściowym `-ss`):
  `atrim=start=tin:end=tout,asetpts=PTS-STARTPTS,adelay=<ms>,volume=<Głośność>`,
- `amix=inputs=k:normalize=0:duration=first` (bez normalizacji, bo amix domyślnie ścisza).

Czasy: wejście 0 jest przesunięte wejściowym `-ss pre`, więc `adelay` = `at − pre`; Podkład
zaczynający się przed `pre` dostaje większe `tin` zamiast ujemnego opóźnienia. Wyjściowe
`-ss`/`-t` tną zmiksowaną ścieżkę tak samo jak wideo. Kodek: AAC `MIX_AUDIO_RATE` (192k) w Ciachu;
w Małym Ciachu plan dostaje `audio_streams >= 2`, żeby nigdy nie wybrał kopii, i bierze bitrate
z drabinki. Weryfikacja: `tests/test_sekwencja.py` mierzy `volumedetect` w oknach, gdzie Podkład
ma być słyszalny i gdzie ma być cisza.
