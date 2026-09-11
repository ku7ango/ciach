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
