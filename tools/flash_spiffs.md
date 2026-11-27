# Flashing a pattern image to the table (reversible)

Write the modified storage partition over USB. App and bootloader are untouched.

    PY='C:\Users\bill\AppData\Local\WillyGarage\oasis\venv\Scripts\python.exe'
    # load our pattern:
    & $PY -m esptool -p COM3 -b 230400 write-flash 0x510000 <build\spiffs-with-90001.bin>
    # undo (restore factory storage):
    & $PY -m esptool -p COM3 -b 230400 write-flash 0x510000 <backup\spiffs.bin>

0x510000 is the spiffs/LittleFS partition; the image is exactly its size
(0xAE0000). A full-chip restore is `write-flash 0 oasis-mini-fw3.16-full-16MB.bin`.
