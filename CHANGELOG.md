# Changelog

Sekcja dla tagu `vX.Y` trafia do opisu release'u na GitHubie (workflow `release.yml`).

## v1.1

### Sklejanie nagrań (Sekwencja)

- Przeciągnij kolejny MP4 na timeline: podczas przeciągania na początku, końcu i na każdym
  styku pojawiają się gniazda. Upuszczenie w gniazdo wstawia nagranie w to miejsce, kilka
  plików naraz wchodzi w kolejności nazw. Upuszczenie na film nadal podmienia całą sesję.
- Sklejanie bez przekodowania (concat), trwa sekundy. Nagrania muszą mieć tę samą
  rozdzielczość, kodek, format pikseli i takie samo audio; fps może się różnić.
- Suwaki po sklejeniu obejmują całość, wynik nazywa się po pierwszym nagraniu, tytuł okna
  pokazuje `+N`. Delete bez zaznaczenia usuwa nagranie pod playheadem.
- Działa też dla MP3 z MP3.

### Podkład (muzyka pod wideo)

- Przeciągnij MP3 na pasek pod timeline'em: powstaje osobny wiersz z podkładem od początku
  filmu. Każdy kolejny MP3 to kolejny wiersz.
- Środek: przesuwanie. Krawędź: przycinanie (muzyka zostaje na miejscu). Krawędzie przyciągają
  się do styków, suwaków, playheada, początku i końca filmu oraz innych podkładów; Ctrl
  wyłącza przyciąganie.
- Zaznaczony podkład albo krawędź: ←/→ o klatkę, Shift o 1 s, Home/End do początku/końca,
  Delete usuwa. ↑/↓: głośność podkładu (5 %, Shift 1 %), bez zaznaczenia głośność filmu.
- Podkład może wystawać za koniec filmu; timeline się wtedy wydłuża.
- Przy ciachu dźwięk filmu i podkłady miksują się do jednej ścieżki AAC 192 kbit/s. Bez
  podkładów i przy głośności 100 % dźwięk jest kopiowany 1:1 jak dotąd. Mały ciach też
  miksuje.

### Poprawki

- Sklejka 30 + 60 fps nie gubi klatek przy ciachu (baza czasu kodera z kontenera).
- Dołączanie trzeciego i kolejnych nagrań do sekwencji nie jest już odrzucane przez
  zafałszowany „średni fps” pliku tymczasowego.
- Skrypty testowe UI celują wyłącznie w okno uruchomione przez test (po PID), nigdy w okno
  użytkownika.

## v1.0

- Pierwsze wydanie: trimmer MP4/MP3 z dwoma suwakami, Ciach (Enter, pełna jakość) i Mały
  Ciach (Ctrl+Enter, plik do 25 MB), waveform, zoom, pętla między suwakami, NVENC z
  fallbackiem na x264.
