# Sekwencja to jeden plik tymczasowy sklejony przez ffmpeg

Podgląd w Ciachu to jeden element `<video>` grający plik źródłowy przez HTTP Range, a cały timeline
(indeksy Klatek, waveform, pętla, eksport) zakłada jedno Nagranie. Gdy użytkownik skleja kilka Nagrań
w Sekwencję, ffmpeg łączy je bez przekodowania (`concat` + `-c copy`) do pliku w katalogu tymczasowym
systemu, a aplikacja ładuje ten plik dokładnie tak, jak dotąd ładowała pojedyncze Nagranie.
Wybraliśmy to zamiast przełączania `video.src` na Styku (zamrożony obraz na granicy, niedokładny seek,
eksport składany z wielu wejść) i zamiast dwóch elementów `<video>` z prebufferowaniem (najwięcej kodu
i synchronizacji), bo dokładność klatkowa i brak nowego kodu w pipeline cięcia są warte kilku sekund
sklejania po dropie i podwojonego miejsca na dysku na czas sesji.

## Consequences

- Sklejać można tylko Nagrania o tych samych parametrach (kodek, rozdzielczość, format pikseli,
  ścieżki audio, kodek audio, częstotliwość i kanały); niezgodne są odrzucane, nie przekodowywane.
  Fps nie jest sprawdzany: sklejka o mieszanym fps jest zmiennoklatkowa, a eksport trzyma bazę
  czasu z kontenera, żeby nie gubić klatek.
- Sygnatura Sekwencji pochodzi z pierwszego Nagrania, nie z pliku tymczasowego: wartości
  wyliczane przez ffprobe dla sklejki (np. średni fps 29,95 zamiast 30) różnią się od źródeł.
- Po każdej zmianie Sekwencji (dodanie, usunięcie Nagrania) plik tymczasowy powstaje od nowa, a w tym
  czasie Ciach, Mały Ciach i kolejne dropy są zablokowane.
- Sekwencja z jednym Nagraniem nie tworzy pliku tymczasowego.
- Pliki tymczasowe kasowane są przy zamknięciu okna i przy podmianie sesji.
