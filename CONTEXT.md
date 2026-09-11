# Ciach

Trimmer plików MP4/MP3: użytkownik zaznacza fragment nagrania i zapisuje go do nowego pliku.
Słownik pojęć używanych w komunikatach, nazwach plików, kodzie i dokumentacji.

## Language

**Nagranie**:
Plik MP4 lub MP3 wczytany do aplikacji, aktualnie widoczny na timeline.
_Avoid_: film, plik źródłowy, wsad, media

**Klatka**:
Najmniejsza jednostka pozycji na timeline. Dla wideo to klatka obrazu, dla MP3 ramka audio (1152 próbek).
_Avoid_: frame, tick, krok

**Suwak**:
Jeden z dwóch znaczników na timeline (lewy i prawy) wyznaczających granice Fragmentu. Lewy włącznie, prawy wyłącznie.
_Avoid_: uchwyt, marker, in/out point, handle

**Fragment**:
Zakres Nagrania między Suwakami, wyrażony w Klatkach. Zawsze co najmniej jedna Klatka.
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
