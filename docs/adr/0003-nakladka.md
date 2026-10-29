# Nakładka: klucz w shaderze podglądu i w ffmpeg, nałożona przed Zbliżeniem

Nakładka (MP4 z zielonym tłem) ma być widoczna na podglądzie od razu z wyciętym tłem i wyglądać tak
samo w wyniku Ciachu. Podgląd to `<video>` w WebView2, a wynik liczy ffmpeg, więc ten sam klucz jest
zaimplementowany dwa razy: w podglądzie płótno WebGL (`#nk`) nad filmem rysuje każdą widoczną Nakładkę
z jej własnego, niewidocznego `<video>` przez shader, a w Ciachu `chromakey` + `despill` + `overlay`.
Oba liczą to samo: odległość chrominancji (U, V) piksela od Koloru klucza, uśrednioną z 3×3 próbek
chrominancji, alfa = (odległość − similarity) / blend, potem zieleń przycięta do średniej czerwieni
i niebieskiego. Wzory obu filtrów sprawdziliśmy na pojedynczych pikselach, zanim powstał shader.

Kolor klucza wybiera się w podglądzie (RGB), a `chromakey` porównuje surowe YUV pliku i sam przelicza
kolor RGB zawsze macierzą BT.601. Dla nagrań BT.709 (OBS) wybrany kolor trafiałby obok tła, więc
Python przelicza go macierzą i zakresem Nakładki (z ffprobe; bez znacznika HD = BT.709, SD = BT.601)
i podaje `chromakey` z `yuv=1`. Shader przelicza piksele tymi samymi współczynnikami (`MATRIX` w obu
plikach).

Nakładka jest częścią obrazu: `overlay` stoi na wejściu 0 **przed** łańcuchem Zbliżenia, a w podglądzie
`#nk` dostaje ten sam transform co `<video>`, więc Zbliżenie powiększa Nakładkę razem z obrazem.
Położenie Nakładki (środek, szerokość, obrót) jest stałe; wyraża się w ułamkach obrazu Sekwencji.

Rozważane alternatywy:

- **`colorkey` w RGB** zamiast `chromakey`: prostszy do odtworzenia w shaderze (jeden piksel, bez
  macierzy), ale odległość w RGB zależy od jasności, więc cień na zielonym tle zostaje. Greenscreen z
  nierównym światłem wymaga porównania samej chrominancji.
- **Kolor klucza próbkowany przez ffmpeg** (surowe YUV klatki): wynik byłby dokładny bez zgadywania
  macierzy, ale podgląd i tak liczy z RGB przeglądarki, a pipeta czekałaby na proces ffmpeg.
- **Nakładka nad Zbliżeniem** (jak facecam, który stoi w miejscu): wybraliśmy, że Nakładka jest częścią
  obrazu i Zbliżenie ją powiększa.

## Consequences

- Podgląd i wynik zgadzają się, dopóki dekoder WebView2 przelicza YUV tą samą macierzą, którą zakłada
  `Media.probe`. Pliki z OBS mają znacznik, więc to się zgadza; dla nieoznaczonych możliwa drobna różnica
  krawędzi klucza, którą usuwa wybranie koloru pipetą (G + klik).
- Nakładka gra w czasie Sekwencji, a `overlay` działa w czasie pliku (przed wycięciem dziur Wycięć, bo
  tam też stoi sendcmd Zbliżenia). Drugi `setpts` rozsuwa klatki Nakładki o każdą dziurę przed nimi
  (odwrotność `Fragment.cut_filters`), więc po wycięciu dziur Nakładka jest ciągła przez szew.
- Każda Nakładka to dodatkowe wejście ffmpeg dla obrazu (z wejściowym `-ss` tuż przed potrzebnym
  kawałkiem) i, gdy ma dźwięk, drugie dla dźwięku w torze miksu (jak Podkład). Ciach z Nakładką z
  dźwiękiem zawsze koduje dźwięk do AAC.
- Podgląd ma jeden `<video>` na Nakładkę, dosuwany do Playheada jak `<audio>` Podkładu (dryf do 120 ms
  w trakcie odtwarzania); na pauzie stoi na Klatce pod Playheadem. Element musi być w DOM (niewidoczny),
  żeby dekoder dawał klatki do tekstury.
- Usunięcie Podkładu i Nakładki stało się krokiem Cofnięcia: UI nie każe już backendowi zapominać
  Podkładu, a migawka trzyma same obiekty z ich elementami audio/wideo.
