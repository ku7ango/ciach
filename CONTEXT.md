# Ciach

Trimmer plików MP4/MP3: użytkownik skleja nagrania, podkłada muzykę, zaznacza fragment i zapisuje go do nowego pliku.
Słownik pojęć używanych w komunikatach, nazwach plików, kodzie i dokumentacji.

## Language

**Nagranie**:
Jeden plik MP4 lub MP3 wczytany do aplikacji. Sekwencja i Podkłady składają się z Nagrań.
_Avoid_: film, plik źródłowy, wsad, media, klip

**Sekwencja**:
Uporządkowany ciąg Nagrań tego samego rodzaju sklejonych koniec do końca. To ona jest na timeline i z niej wycinany jest Fragment. Nagrania w Sekwencji muszą mieć te same parametry obrazu i dźwięku (kodek, rozdzielczość, format pikseli, ścieżki audio); fps może się różnić.
_Avoid_: sklejka, montaż, projekt, lista

**Styk**:
Granica między dwoma sąsiednimi Nagraniami w Sekwencji. Cel Przyciągania i miejsce Gniazda.
_Avoid_: szew, granica, cięcie, boundary

**Gniazdo**:
Miejsce, w które można upuścić przeciągany plik: na Stykach i obu końcach Sekwencji (nowe Nagranie) albo w pasku pod ścieżkami (nowy Podkład). Widoczne tylko podczas przeciągania.
_Avoid_: strefa, drop zone, okienko, slot

**Podkład**:
Nagranie MP3 ułożone w osobnym wierszu pod Sekwencją wideo, z własną pozycją, Krawędziami i Głośnością. Jeden wiersz = jeden Podkład. Przy Ciachu miksuje się z dźwiękiem Sekwencji.
_Avoid_: ścieżka, muzyka, track, warstwa, tło

**Krawędź**:
Lewy lub prawy brzeg Podkładu. Przesunięcie Krawędzi przycina Podkład (treść zostaje na miejscu), przesunięcie środka przesuwa cały Podkład.
_Avoid_: uchwyt, brzeg, in/out, handle

**Przyciąganie**:
Automatyczne dociąganie Krawędzi przesuwanego Podkładu do Styku, Suwaka, końca Sekwencji lub Krawędzi innego Podkładu, gdy znajdzie się blisko. Ctrl wyłącza.
_Avoid_: snap, magnes, dopasowanie

**Głośność**:
Poziom dźwięku Podkładu albo całej Sekwencji, od 0 % (cisza) do 100 %. Zmieniana strzałkami ↑/↓ na zaznaczonym elemencie. Wchodzi w miks przy Ciachu.
_Avoid_: volume, gain, poziom, wzmocnienie

**Klatka**:
Najmniejsza jednostka pozycji na timeline. Dla wideo to klatka obrazu, dla MP3 ramka audio (1152 próbek). Pozycje Podkładów i ich Krawędzi też są wyrażone w Klatkach Sekwencji.
_Avoid_: frame, tick, krok

**Suwak**:
Jeden z dwóch znaczników na timeline (lewy i prawy) wyznaczających granice Fragmentu. Lewy włącznie, prawy wyłącznie. Przechodzą przez wszystkie wiersze.
_Avoid_: uchwyt, marker, in/out point, handle

**Fragment**:
Zakres Sekwencji między Suwakami, wyrażony w Klatkach. Zawsze co najmniej jedna Klatka.
_Avoid_: zaznaczenie, wycinek, region, selekcja, klip

**Playhead**:
Bieżąca pozycja odtwarzania na timeline.
_Avoid_: kursor, głowica, pozycja

**Ciach**:
Zapis Fragmentu do nowego pliku w pełnej jakości. Wynik ląduje obok aplikacji.
_Avoid_: eksport, trim, wycięcie, render, zapis

**Mały Ciach**:
Ciach z Limitem rozmiaru: Fragment zapisany tak, żeby plik nie przekroczył zadanej liczby bajtów, kosztem jakości.
_Avoid_: kompresja, ciach na Messengera, ciach 25, wersja skompresowana

**Limit rozmiaru**:
Maksymalna liczba bajtów pliku wynikowego Małego Ciachu. Domyślnie wynika z ograniczeń Messengera.
_Avoid_: budżet, cap, rozmiar docelowy
