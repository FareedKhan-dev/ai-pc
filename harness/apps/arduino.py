"""Arduino (the IDE students and makers everywhere use; its own engine, arduino-cli 1.5.1 with the AVR boards, lives in
tools/arduino): a sketch written from words (blink, traffic lights, button and LED, knob/sensor to LED and Serial,
ultrasonic distance alarm, LM35 temperature with a fan, PIR motion alarm) or a .ino given, really compiled for an Uno,
Nano or Mega, with a wiring list. Uploading to a board on a USB port is shown first and done only after a yes.
Checked: it compiles, fits the board's flash and memory, the .hex is made, and no pin is used twice (PWM only on PWM pins).

  'arduino traffic light on a nano, green 5 seconds'   'arduino ultrasonic alarm closer than 20 cm'   'upload it to the arduino'
"""
import json
import re
import shutil
import subprocess
from pathlib import Path

from ..config import ROOT

NAME, LABEL = "arduino", "Arduino: sketches from words, compiled for Uno/Nano/Mega, upload after a yes"
EXAMPLES = ["arduino blink pin 7 every 200 ms", "arduino traffic light on a nano, green 5 seconds", "arduino ultrasonic alarm closer than 20 cm",
            "upload it to the arduino"]
CLI = ROOT / "tools" / "arduino" / "arduino-cli.exe"
CONFIG = ROOT / "tools" / "arduino" / "arduino-cli.yaml"
BOARDS = {"uno": "arduino:avr:uno", "nano": "arduino:avr:nano:cpu=atmega328", "mega": "arduino:avr:mega:cpu=atmega2560"}
PWM = {"uno": {3, 5, 6, 9, 10, 11}, "nano": {3, 5, 6, 9, 10, 11}, "mega": set(range(2, 14)) | {44, 45, 46}}
OUTWARD = {"upload"}

SKETCHES = {
    "blink": ("Blink", {"LED": 13}, """// Blink an LED (made by AI PC)
const int LED = {LED};
const unsigned long WAIT_MS = {ms};

void setup() {
  pinMode(LED, OUTPUT);
}

void loop() {
  digitalWrite(LED, HIGH);
  delay(WAIT_MS);
  digitalWrite(LED, LOW);
  delay(WAIT_MS);
}
""", 500),
    "traffic": ("TrafficLight", {"RED": 10, "YELLOW": 9, "GREEN": 8}, """// Traffic light (made by AI PC)
const int RED = {RED}, YELLOW = {YELLOW}, GREEN = {GREEN};
const unsigned long GREEN_MS = {ms}, YELLOW_MS = 2000, RED_MS = {ms};

void show(int r, int y, int g, unsigned long ms) {
  digitalWrite(RED, r);
  digitalWrite(YELLOW, y);
  digitalWrite(GREEN, g);
  delay(ms);
}

void setup() {
  pinMode(RED, OUTPUT);
  pinMode(YELLOW, OUTPUT);
  pinMode(GREEN, OUTPUT);
}

void loop() {
  show(HIGH, LOW, LOW, RED_MS);
  show(HIGH, HIGH, LOW, 1000);
  show(LOW, LOW, HIGH, GREEN_MS);
  show(LOW, HIGH, LOW, YELLOW_MS);
}
""", 5000),
    "button": ("ButtonLed", {"BUTTON": 2, "LED": 13}, """// A button turns the LED on and off (made by AI PC)
const int BUTTON = {BUTTON}, LED = {LED};
bool on = false;
int last = HIGH;

void setup() {
  pinMode(BUTTON, INPUT_PULLUP);  // the button joins the pin to GND, no resistor needed
  pinMode(LED, OUTPUT);
}

void loop() {
  int now = digitalRead(BUTTON);
  if (last == HIGH && now == LOW) {
    on = !on;
    digitalWrite(LED, on ? HIGH : LOW);
    delay(30);  // debounce
  }
  last = now;
}
""", 0),
    "knob": ("KnobToLed", {"SENSOR": "A0", "LED": 9}, """// A knob or sensor sets the LED brightness and is printed to Serial (made by AI PC)
const int SENSOR = {SENSOR}, LED = {LED};

void setup() {
  Serial.begin(9600);
  pinMode(LED, OUTPUT);
}

void loop() {
  int value = analogRead(SENSOR);
  analogWrite(LED, map(value, 0, 1023, 0, 255));
  Serial.println(value);
  delay({ms});
}
""", 100),
    "ultrasonic": ("DistanceAlarm", {"TRIG": 9, "ECHO": 10, "ALERT": 13}, """// HC-SR04 distance with an alarm when something is close (made by AI PC)
const int TRIG = {TRIG}, ECHO = {ECHO}, ALERT = {ALERT};
const float NEAR_CM = {near};

void setup() {
  Serial.begin(9600);
  pinMode(TRIG, OUTPUT);
  pinMode(ECHO, INPUT);
  pinMode(ALERT, OUTPUT);
}

void loop() {
  digitalWrite(TRIG, LOW);
  delayMicroseconds(2);
  digitalWrite(TRIG, HIGH);
  delayMicroseconds(10);
  digitalWrite(TRIG, LOW);
  unsigned long us = pulseIn(ECHO, HIGH, 30000UL);
  float cm = us / 58.0;
  Serial.print("Distance: ");
  Serial.print(cm);
  Serial.println(" cm");
  digitalWrite(ALERT, (us > 0 && cm < NEAR_CM) ? HIGH : LOW);
  delay({ms});
}
""", 200),
    "temperature": ("TemperatureFan", {"SENSOR": "A0", "FAN": 8}, """// LM35 temperature, a fan (through a relay or transistor) on when hot (made by AI PC)
const int SENSOR = {SENSOR}, FAN = {FAN};
const float HOT_C = {hot};

void setup() {
  Serial.begin(9600);
  pinMode(FAN, OUTPUT);
}

void loop() {
  float c = analogRead(SENSOR) * (5000.0 / 1023.0) / 10.0;  // LM35: 10 mV per degree
  Serial.print("Temperature: ");
  Serial.print(c);
  Serial.println(" C");
  digitalWrite(FAN, c > HOT_C ? HIGH : LOW);
  delay({ms});
}
""", 1000),
    "motion": ("MotionAlarm", {"PIR": 2, "ALARM": 13}, """// PIR motion alarm (made by AI PC)
const int PIR = {PIR}, ALARM = {ALARM};

void setup() {
  Serial.begin(9600);
  pinMode(PIR, INPUT);
  pinMode(ALARM, OUTPUT);
}

void loop() {
  bool moving = digitalRead(PIR) == HIGH;
  digitalWrite(ALARM, moving ? HIGH : LOW);
  if (moving) Serial.println("Motion!");
  delay({ms});
}
""", 100),
}
KINDS = {"traffic": r"traffic", "ultrasonic": r"ultrasonic|distance|hc-?sr04|parking", "temperature": r"temperature|lm35|\bfan\b",
         "motion": r"motion|\bpir\b", "button": r"button|switch|push", "knob": r"knob|potentiometer|\bpot\b|analog|light sensor|ldr|dimm", "blink": r"blink|flash|led"}
WIRING = {"LED": "LED (+) through a 220 ohm resistor; LED (-) to GND", "RED": "red LED through 220 ohm to GND", "YELLOW": "yellow LED through 220 ohm to GND",
          "GREEN": "green LED through 220 ohm to GND", "BUTTON": "push button to GND", "SENSOR": "sensor/knob middle pin (outer pins to 5V and GND)",
          "TRIG": "HC-SR04 Trig (Vcc to 5V, GND to GND)", "ECHO": "HC-SR04 Echo", "ALERT": "buzzer or LED (+), (-) to GND", "FAN": "relay/transistor input for the fan",
          "PIR": "PIR OUT (VCC to 5V, GND to GND)", "ALARM": "buzzer or LED (+), (-) to GND"}
PWM_ROLES = {"knob": {"LED"}}


def cli(*args, timeout=600):
    return subprocess.run([str(CLI), "--config-file", str(CONFIG), *args], capture_output=True, text=True, timeout=timeout,
                          creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))


def read(text):
    c = text.lower()
    kind = next((k for k, p in KINDS.items() if re.search(p, c)), "blink")
    title, pins, _, ms = SKETCHES[kind]
    pins = dict(pins)
    roles = {"LED": r"led|light", "BUTTON": r"button|switch", "SENSOR": r"sensor|knob|potentiometer|pot|lm35", "TRIG": r"trig", "ECHO": r"echo",
             "ALERT": r"buzzer|alert|alarm", "ALARM": r"buzzer|alarm|alert", "FAN": r"fan|relay", "PIR": r"pir|motion", "RED": r"red", "YELLOW": r"yellow", "GREEN": r"green"}
    for role in pins:
        m = re.search(r"\b(?:" + roles[role] + r")\w*\s+(?:on\s+|at\s+|to\s+)?pin\s+(A?\d{1,2})\b", c, re.I)
        if m:
            pins[role] = m.group(1).upper() if m.group(1).lower().startswith("a") else int(m.group(1))
    m = re.search(r"\bpin\s+(\d{1,2})\b", c)
    if m and kind == "blink" and not re.search(r"\b(?:led|light)\w*\s+(?:on\s+|at\s+)?pin", c):
        pins["LED"] = int(m.group(1))
    t = re.search(r"\b(\d+(?:\.\d+)?)\s*(ms|milliseconds?|s|secs?|seconds?)\b", c)
    if t:
        ms = int(float(t.group(1)) * (1 if t.group(2).startswith("m") else 1000))
    near = re.search(r"\b(\d+)\s*cm\b", c)
    hot = re.search(r"\b(?:above|over|hotter than|more than)\s+(\d+)|\b(\d+)\s*(?:°\s*)?c\b(?!m)", c)
    board = next((b for b in BOARDS if re.search(rf"\b{b}\b", c)), "uno")
    return {"kind": kind, "title": title, "pins": pins, "ms": ms, "near": int(near.group(1)) if near else 20,
            "hot": int(hot.group(1) or hot.group(2)) if hot else 30, "board": board}


def sketch(spec):
    code = SKETCHES[spec["kind"]][2]
    for k, v in {**spec["pins"], "ms": spec["ms"], "near": spec["near"], "hot": spec["hot"]}.items():
        code = code.replace("{" + k + "}", str(v))
    return code


def wiring(spec):
    return [f"pin {v}: {WIRING[k]}" for k, v in spec["pins"].items()]


def compile_sketch(folder, board):
    build = Path(folder) / "build"
    r = cli("compile", "--fqbn", BOARDS[board], "--build-path", str(build), "--format", "json", str(folder))
    try:
        j = json.loads(r.stdout)
    except ValueError:
        j = {"success": False, "compiler_err": (r.stderr or r.stdout)[-800:]}
    return j, build


def check(j, build, name, spec):
    sizes = {s["name"]: s for s in (j.get("builder_result") or {}).get("executable_sections_size") or []}
    out = [("it compiles", bool(j.get("success"))),
           ("it fits the board's flash and memory", bool(sizes) and all(s["size"] <= s["max_size"] for s in sizes.values())),
           ("the .hex for the board is made", (build / f"{name}.ino.hex").exists())]
    if spec:
        pins = list(spec["pins"].values())
        pwm_ok = all(spec["pins"][r] in PWM[spec["board"]] for r in PWM_ROLES.get(spec["kind"], ()))
        out.append(("no pin used twice, PWM only on PWM pins", len(pins) == len(set(map(str, pins))) and pwm_ok))
    return out, sizes


def parse(text, ctx):
    from .appschat import find_file
    c = text.lower()
    memo = (ctx.get("memo") or {}).get("arduino")
    if re.search(r"\bupload\b", c) and (re.search(r"\barduino\b", c) or memo):
        port = re.search(r"\b(com\d+)\b", c)
        return {"op": "upload", "port": port.group(1).upper() if port else None}
    if not re.search(r"\barduino\b", c):
        return None
    if re.search(r"\b(?:boards?|ports?)\b.*\b(?:connected|plugged|list|which)\b|\b(?:list|which|connected)\b.*\b(?:boards?|ports?)\b", c):
        return {"op": "boards"}
    f = find_file(text, ctx, {".ino"})
    if f:
        board = next((b for b in BOARDS if re.search(rf"\b{b}\b", c)), "uno")
        return {"op": "compile", "file": f, "board": board}
    return {"op": "make", "spec": read(text)}


def boards():
    r = cli("board", "list", "--format", "json", timeout=60)
    try:
        j = json.loads(r.stdout or "{}")
    except ValueError:
        return []
    ports = j.get("detected_ports", j) if isinstance(j, dict) else j
    out = []
    for p in ports or []:
        addr = (p.get("port") or {}).get("address")
        names = [b.get("name") for b in p.get("matching_boards") or []]
        if addr:
            out.append((addr, names[0] if names else None))
    return out


def preview(op, ctx):
    last = (ctx.get("memo") or {}).get("arduino")
    if not last:
        op["blocked"] = True
        return "Make a sketch first, e.g. 'arduino blink pin 13'."
    port = op.get("port") or next((a for a, n in boards() if n), None)
    op["port"] = port
    if not port:
        op["blocked"] = True
        return "No Arduino found on a USB port: plug it in (and close the Arduino IDE's Serial Monitor), then say 'upload it to the arduino'."
    return f"Ready to upload {last['name']} to the {last['board'].title()} on {port}: it replaces the program on the board."


def run(op, ctx):
    memo = ctx.setdefault("memo", {})
    if op["op"] == "boards":
        found = boards()
        return ("Boards on USB: " + "; ".join(f"{a}: {n or 'unknown board (a clone: pick uno/nano/mega)'}" for a, n in found) + ".") if found else \
            "No board on a USB port right now (plug it in; clones need the CH340 driver)."
    if op["op"] == "upload":
        last = memo.get("arduino")
        if not last or not op.get("port"):
            return preview(op, ctx)
        r = cli("upload", "-p", op["port"], "--fqbn", BOARDS[last["board"]], "--input-dir", str(Path(last["folder"]) / "build"), last["folder"], timeout=180)
        ok = r.returncode == 0
        return f"Uploaded {last['name']} to {op['port']}." if ok else f"Upload failed: {(r.stderr or r.stdout).strip()[-300:]}"
    out = Path(ctx["out"]) / "arduino"
    if op["op"] == "compile":
        src = Path(op["file"])
        folder = out / src.stem
        folder.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, folder / src.name)  # arduino-cli wants the sketch in a folder of its own name
        name, spec, board, notes = src.stem, None, op["board"], []
    else:
        spec = op["spec"]
        name, board = spec["title"], spec["board"]
        folder = out / name
        folder.mkdir(parents=True, exist_ok=True)
        (folder / f"{name}.ino").write_text(sketch(spec), encoding="utf-8")
        notes = wiring(spec)
        (folder / "wiring.txt").write_text("\n".join(notes) + "\n", encoding="utf-8")
    j, build = compile_sketch(folder, board)
    checks, sizes = check(j, build, name, spec)
    bad = [w for w, ok in checks if not ok]
    memo["arduino"] = {"folder": str(folder), "name": name, "board": board}
    use = f" Uses {sizes['text']['size']:,} of {sizes['text']['max_size']:,} bytes of flash." if "text" in sizes else ""
    return (f"Arduino sketch {name} for the {board.title()}: {folder / (name + '.ino')}." + use +
            (" Wiring: " + "; ".join(notes) + "." if notes else "") +
            (" Checked: " + "; ".join(w for w, _ in checks) + "." if not bad else " NOT right: " + "; ".join(bad) + ". " + (j.get("compiler_err") or "")[-400:]) +
            " Say 'upload it to the arduino' with the board plugged in; it opens in the Arduino IDE too.")
