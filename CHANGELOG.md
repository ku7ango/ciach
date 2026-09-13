# Changelog

Sekcja dla tagu `vX.Y` trafia do opisu release'u na GitHubie (workflow `release.yml`).

## v1.3

### Wycięcie (usuwanie kawałka nagrania)

- **C** stawia wycięcie w playheadzie (czerwony pas z dwiema krawędziami), kolejne **C**
  dociąga bliższą krawędź do playheada; krawędzie da się też przeciągać myszą z przyciąganiem.
  **Delete** wycina, **Esc** porzuca. Odtwarzanie przy istniejącym wycięciu pomija je, więc
  wynik słychać przed decyzją. Ciach, zbliżenia, głośność i dropy czekają, aż wycięcie zostanie
  wykonane albo porzucone; suwaki wolno przesuwać.
- Wycięcie na filmie: obraz, suwaki i zbliżenia za nim jadą w lewo, nachodzące zbliżenie jest
  skracane, podkłady trzymają się swojej klatki obrazu. Miejsce cięcia to styk: nagranie rozpada
  się na dwa (tytuł `+N`), między nimi jest gniazdo. Przy zaznaczonym podkładzie **C** wycina
  kawałek muzyki (reszta dosuwa się).
- **Ctrl+Z** cofa wykonane wycięcia i usunięcia nagrań, dowolnie wiele, aż do ostatniego
  wstawienia nagrania.
- Delete nagrania działa jak wycięcie całego nagrania: suwaki i zbliżenia za nim jadą z obrazem
  (dotąd suwaki wracały na całość, a nachodzące zbliżenia znikały).
- Wycięcie nie dotyka dysku: wynik składa ffmpeg przy ciachu (obraz `select`/`setpts`, dźwięk
  `atrim`/`concat`; mp3 bez strat). Ciach fragmentu ze szwem koduje dźwięk do AAC 192 kbit/s;
  w podglądzie na szwie odtwarzanie zacina się na ułamek sekundy. ADR 0002.

## v1.2

### Zbliżenie (powiększenie fragmentu obrazu)

- Z + przeciągnięcie po obrazie rysuje Kadr i tworzy zbliżenie o długości jednej klatki.
  Na dalszych klatkach złap szary cień Kadru, żeby wydłużyć zbliżenie; na każdej klatce
  zbliżenia Kadr da się przesunąć (środek) i przeskalować (róg), a ustawiona pozycja jest
  zapamiętana w tej klatce. Między pozycjami Kadr przejeżdża (przerywana linia), poza nimi
  stoi. Kadr trzyma proporcje filmu, najmniejszy 20 % szerokości (5×).
- Z + przeciągnięcie wewnątrz zbliżenia rozcina je na dwa stykające się ze sobą.
- Zbliżenia mają własny wiersz na timeline: środek przesuwa, krawędź zmienia długość, górny
  róg wyciąga rampę (płynne wejście/wyjście). Przyciąganie jak przy podkładzie, Ctrl wyłącza.
  Nie nachodzą na siebie.
- W trakcie odtwarzania podgląd pokazuje zbliżenie jak w wyniku; na pauzie cały obraz z Kadrem.
- Przy zaznaczonym zbliżeniu ←/→ i Home/End chodzą po klatkach; zbliżenie, krawędź albo rampę
  przesuwa Ctrl+←/→ (Ctrl+Shift: 1 s). Delete usuwa (na rampie: zeruje rampę), Esc odznacza.
- Ciach i mały ciach powiększają Kadr do rozdzielczości źródła; bez zbliżeń polecenia
  ffmpeg są takie jak dotąd.
- Ekran startowy wymienia wszystkie skróty.

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
