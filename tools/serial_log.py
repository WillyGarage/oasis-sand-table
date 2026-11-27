"""Reset the table (same RTS pulse esptool uses for a normal restart) and print what it logs on
its USB serial port. Read-only. Usage: serial_log.py COM3 [seconds] [baud]"""
import sys, time, serial
port = sys.argv[1]; secs = float(sys.argv[2]) if len(sys.argv) > 2 else 25; baud = int(sys.argv[3]) if len(sys.argv) > 3 else 115200
s = serial.Serial(); s.port = port; s.baudrate = baud; s.timeout = 0.2; s.dtr = False; s.rts = False; s.open()
s.dtr = False; s.rts = True; time.sleep(0.1); s.rts = False   # EN low then high: normal boot (IO0 not held)
t0 = time.time(); buf = b""
while time.time() - t0 < secs:
    buf += s.read(4096)
s.close()
sys.stdout.buffer.write(buf)
