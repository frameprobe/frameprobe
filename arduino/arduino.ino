#include <Adafruit_NeoPixel.h>
#include "mouse16.h"

#define FIRMWARE_VERSION "1.2.0"

#define NUMPIXELS 1

Adafruit_NeoPixel pixelLED(NUMPIXELS, PIN_NEOPIXEL, NEO_GRB + NEO_KHZ800);

// override arduino-pico's weak default of 10 (USB.cpp) — a 10ms HID bInterval
// adds a uniform 0-10ms host-poll delay to every measurement; 1ms matches a
// 1000Hz gaming mouse
int usb_hid_poll_interval = 1;

void setup() {
  // init serial
  Serial.begin(115200);
  while(!Serial); // wait for device to come online
  delay(2000); // Give time for USB to stabilize

  // init neopixel (NEOPIXEL_POWER only exists on boards with a switched
  // NeoPixel rail like the QT Py; the RP2040-Zero powers it directly)
#ifdef NEOPIXEL_POWER
  pinMode(NEOPIXEL_POWER, OUTPUT);
  digitalWrite(NEOPIXEL_POWER, HIGH);
#endif

  pixelLED.begin();
  pixelLED.setBrightness(20);
  pixelLED.setPixelColor(0, pixelLED.Color(255, 0, 0));
  pixelLED.show();

  analogReadResolution(14); // set ADC resolution to 14 bits (0-16383)

  // seed RNG from ADC noise — unseeded random() repeats the same sequence every
  // boot, which would make the inter-click jitter identical across sessions
  uint32_t seed = micros();
  for (int i = 0; i < 32; i++) {
    seed = (seed << 1) ^ analogRead(A1);
  }
  randomSeed(seed);

  // init mouse
  Mouse16.begin();
}

bool isRunning = false;
bool isDebugRunning = false;
float timeBetweenClicks = 0.5; // seconds
int clickCount = 10;
int currentClickCount = 0;
bool isMoveMode = false;   // false = click mode (default)
int moveDistance = 500;    // HID counts, 1-32767: always one atomic report (16-bit HID axes)
char moveDirection = 'r';  // 'u', 'd', 'l', 'r'

#define SampleCount 12000
#define PreClickSamples 2000 // ~48ms of baseline before click, enough for ADC drift to settle (~12ms)
uint16_t adcBuff[SampleCount];

// read a one-character command argument; the host sends command+arg together,
// but wait up to the serial parse timeout in case the bytes arrive split
char readCharArg() {
  unsigned long start = millis();
  while (!Serial.available() && millis() - start < 1000);
  return Serial.available() ? (char)Serial.read() : '\0';
}

const char* directionName(char d) {
  switch (d) {
    case 'u': return "up";
    case 'd': return "down";
    case 'l': return "left";
    default:  return "right";
  }
}

// map distance + direction to a HID report delta; HID Y is positive-down
void computeMove(int &dx, int &dy) {
  dx = 0;
  dy = 0;
  if (moveDirection == 'r')      dx =  moveDistance;
  else if (moveDirection == 'l') dx = -moveDistance;
  else if (moveDirection == 'u') dy = -moveDistance;
  else                           dy =  moveDistance;
}

void runTest() {
    int currentSampleCount = 0;
    unsigned long startTimer = micros();

    // Phase 1: collect pre-click baseline samples (ADC drift settles within ~12ms)
    while (currentSampleCount < PreClickSamples) {
      adcBuff[currentSampleCount] = analogRead(A1);
      currentSampleCount++;
      delayMicroseconds(20);
    }

    // Phase 2: fire the input event (click or move, depending on mode);
    // dx/dy computed up front so the mapping cost never lands in clickDuration
    int dx, dy;
    computeMove(dx, dy);
    unsigned long clickTime = micros();
    if (isMoveMode) Mouse16.move(dx, dy);
    else Mouse16.press(MOUSE_LEFT);
    unsigned long afterClick = micros();
    unsigned long clickDuration = afterClick - clickTime;

    // Phase 3: collect post-click samples capturing the transition
    while (currentSampleCount < SampleCount) {
      adcBuff[currentSampleCount] = analogRead(A1);
      currentSampleCount++;
      delayMicroseconds(20);
    }

    unsigned long endTimer = micros();
    unsigned long timeTaken = endTimer - startTimer;

    if (!isMoveMode) Mouse16.release(MOUSE_LEFT);

    Serial.print("CSV");
    Serial.print(clickDuration);
    Serial.print(",");
    Serial.print(timeTaken);
    Serial.print(",");
    Serial.print(SampleCount);
    Serial.print(",");
    Serial.print(PreClickSamples); // click sample index so host knows where the click happened
    Serial.print(",");

    for (int i = 0; i < SampleCount; i++) {
      Serial.print(adcBuff[i]);
      Serial.print(";");
    }

    Serial.println();
    Serial.flush(); // wait for serial data to fully transmit before next measurement — HID and CDC share the USB bus, so lingering serial traffic can delay Mouse16.press() delivery

    if (isMoveMode) {
      // return the cursor to its starting position
      Mouse16.move(-dx, -dy);
    }
}

void loop() {
  if (Serial.available()) {
    char cmd = Serial.read();

    if (cmd == '1') {
      pixelLED.setBrightness(0);
      pixelLED.show();

      Serial.println("Starting latency test in 3 seconds...");
      Serial.println("Mode: " + String(isMoveMode ? "move" : "click"));
      if (isMoveMode) {
        Serial.println("Move distance: " + String(moveDistance) + " counts, direction: " + String(directionName(moveDirection)));
      }
      Serial.println("Current time between clicks: " + String(timeBetweenClicks) + " seconds");
      Serial.println("Current click count: " + String(clickCount));

      delay(3000);
      isRunning = true;
    } else if (cmd == '0') {
      isRunning = false;
      isDebugRunning = false;
      currentClickCount = 0;

      Serial.println("Stopped");
      pixelLED.setBrightness(20);
      pixelLED.setPixelColor(0, pixelLED.Color(255, 0, 0));
      pixelLED.show();
    } else if (cmd == 'd') {
      pixelLED.setBrightness(0);
      pixelLED.show();

      Serial.println("Enabled debug mode");
      isDebugRunning = true;
    } else if (cmd == 'i') {
      float newInterval = Serial.parseFloat();
      if (newInterval > 0) {
        timeBetweenClicks = newInterval;
        Serial.println("Interval set to: " + String(timeBetweenClicks) + " seconds");
      } else {
        Serial.println("Invalid interval value");
      }
    } else if (cmd == 'c') {
      long newClickCount = Serial.parseInt();
      if (newClickCount > 0) {
        clickCount = newClickCount;
        Serial.println("click count set to: " + String(clickCount));
      } else {
        Serial.println("Invalid click count value");
      }
    } else if (cmd == 'm') {
      char mode = readCharArg();
      if (mode == 'c' || mode == 'm') {
        isMoveMode = (mode == 'm');
        Serial.println("Mode set to: " + String(isMoveMode ? "move" : "click"));
      } else {
        Serial.println("Invalid mode (mc = click, mm = move)");
      }
    } else if (cmd == 'x') {
      long newDistance = Serial.parseInt();
      if (newDistance >= 1 && newDistance <= 32767) {
        moveDistance = newDistance;
        Serial.println("Move distance set to: " + String(moveDistance) + " counts");
      } else {
        Serial.println("Invalid move distance (1-32767)");
      }
    } else if (cmd == 'r') {
      char dir = readCharArg();
      if (dir == 'u' || dir == 'd' || dir == 'l' || dir == 'r') {
        moveDirection = dir;
        Serial.println("Move direction set to: " + String(directionName(moveDirection)));
      } else {
        Serial.println("Invalid direction (u/d/l/r)");
      }
    } else if (cmd == 't') {
      int dx, dy;
      computeMove(dx, dy);
      Serial.println("Move test: " + String(moveDistance) + " counts " + String(directionName(moveDirection)) + " (resets in 1s)");
      Mouse16.move(dx, dy);
      delay(1000);
      Mouse16.move(-dx, -dy);
    } else if (cmd == 'v') {
      Serial.println("FRAMEPROBE," FIRMWARE_VERSION);
    }
  }

  // unsigned long PERF_start = micros();
  // unsigned long PERF_stop = micros();
  // Serial.print("PERF,");
  // Serial.println(PERF_stop - PERF_start);

  if (isRunning) {
    if (currentClickCount < clickCount) {
      // Serial.println("Click " + String(currentClickCount+1) + " of " + String(clickCount));
      runTest();

      // ±10ms random jitter decorrelates click timing from the display refresh
      // phase — a fixed interval can repeatedly land at the same scanout
      // position. Generated in µs, not ms: whole-ms offsets modulo a 2ms frame
      // period (500Hz) hit only two phases; µs resolution covers all of them.
      long delayUs = (long)(timeBetweenClicks * 1000000.0f) + random(-10000, 10001);
      if (delayUs < 0) delayUs = 0;
      delay(delayUs / 1000);
      delayMicroseconds(delayUs % 1000);
      currentClickCount++;
    } else {
      isRunning = false;
      currentClickCount = 0;
      pixelLED.setBrightness(20);
      pixelLED.setPixelColor(0, pixelLED.Color(255, 0, 0));
      pixelLED.show();

      Serial.println("DONE");
      Serial.flush();
      return;
    }
  }

  if (isDebugRunning) {
    uint16_t raw = analogRead(A1); // 14-bit ADC: 0 - 16383
    float voltage = (raw * 3.3) / 16383.0; // Convert to voltage
    Serial.print("Raw ADC: ");
    Serial.print(raw);
    Serial.print(", Voltage: ");
    Serial.println(voltage, 4);
  }
}
