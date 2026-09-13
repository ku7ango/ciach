# Wycięcie jest wirtualne: Nagranie to zakres pliku, nie plik

Wycięcie ma być dokładne co do Klatki, natychmiastowe i odwracalne. Nagrania użytkownika (H.264 z OBS)
mają klatkę kluczową co ~2 s, więc cięcia na dowolnej Klatce nie da się zrobić kopią strumienia.
Zamiast przebudowywać plik tymczasowy Sekwencji po każdym Wycięciu, Nagranie w Sekwencji staje się
ciągłym zakresem (od–do) wewnątrz sklejonego pliku, a wykonane Wycięcie po prostu dzieli Nagranie na
dwa kawałki i wyrzuca środek. Plik tymczasowy (ADR 0001) zostaje sklejką całych plików źródłowych; cały
timeline, Suwaki, Zbliżenia, Podkłady i pętla liczą w czasie Sekwencji, czyli w Klatkach, które zostały,
a mapowanie na czas pliku dzieje się przy odtwarzaniu i przy budowie polecenia ffmpeg. Ciach składa
wynik z kilku zakresów pliku przez filtr trim/concat. Obraz mp4 i tak jest przy Ciachu przekodowywany,
więc koszt to tylko dźwięk. Usunięcie całego Nagrania klawiszem Delete jest tym samym mechanizmem:
Wycięciem pokrywającym Nagranie.

Rozważane alternatywy:

- **Przebudowa pliku tymczasowego z przekodowaniem przy szwie** (smart cut: tylko grupy klatek wokół
  cięcia kodowane na nowo, reszta kopiowana). Płynny podgląd, ale kilka sekund pracy na każde Wycięcie,
  sklejanie różnie zakodowanych kawałków H.264 bywa niestabilne w dekoderach, najwięcej nowego kodu
  w pipeline i drogie cofanie.
- **Cięcie tylko na klatkach kluczowych** z kopią strumienia. Zero przekodowania, ale dokładność ~2 s,
  co przeczy sterowaniu Klatka po Klatce.

## Consequences

- Wykonanie Wycięcia i Cofnięcie nie dotykają dysku: stan Sekwencji to lista zakresów, Cofnięcie to
  poprzednia lista. Lista cofnięć czyści się przy zmianie składu Sekwencji przez drop i przy nowej sesji.
- Podgląd na szwie po Wycięciu robi seek `<video>`, więc odtwarzanie zacina się tam na ~0,1–0,3 s.
  Wynik Ciachu jest czysty. Gdyby zacięcie okazało się nie do zniesienia, smart cut da się dołożyć
  jako „utwardzenie” Sekwencji bez zmiany modelu.
- Ciach Fragmentu, który zawiera szew po Wycięciu, przekodowuje dźwięk do AAC 192 kbit/s (jak z
  Podkładem). Fragment bez szwu kopiuje dźwięk 1:1 jak dotąd. Mp3 tnie się bez strat, bo ramka mp3
  jest Klatką.
- Czas Sekwencji ≠ czas pliku. Każde miejsce, które przekazuje czas do `<video>`, ffmpeg (seek,
  sendcmd Zbliżeń, offsety Podkładów) albo czyta czas z `<video>`, przechodzi przez mapowanie.
- Upuszczenie pliku w Styk między dwoma kawałkami tego samego pliku wymaga, żeby plik tymczasowy
  zawierał ten plik dwukrotnie (raz na każdy kawałek). Przyjęte świadomie: podwojenie jednego
  Nagrania na czas sesji zamiast wyjątku w Gniazdach.
- Nagranie może być kawałkiem pliku, więc jedna sesja ma wiele Nagrań o tej samej nazwie. Tytuł okna
  i nazwa wyniku pochodzą od pierwszego Nagrania jak dotąd.
- Usunięcie Nagrania przestaje resetować Suwaki na cały zakres i kasować Zbliżenia: Suwaki i Zbliżenia
  za nim przesuwają się z obrazem, Zbliżenia nachodzące są skracane, jak przy każdym Wycięciu.
