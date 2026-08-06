// Minimal replacement for the stock arduino-pico Mouse library with 16-bit
// relative X/Y axes (±32767 per report) instead of 8-bit ±127, so any move
// distance stays a single atomic HID report — chaining ±127 reports would
// smear the input edge across multiple 1ms polls.
#pragma once

#include <Arduino.h>

#define MOUSE_LEFT 1

class Mouse16Device {
  public:
    void begin();
    void press(uint8_t b = MOUSE_LEFT);
    void release(uint8_t b = MOUSE_LEFT);
    void move(int x, int y);
  private:
    void report(int x, int y);
    uint8_t _id = 0;
    uint8_t _buttons = 0;
};

extern Mouse16Device Mouse16;
