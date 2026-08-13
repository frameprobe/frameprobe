#include "mouse16.h"

#include <USB.h>
#include "tusb.h"
#include "class/hid/hid_device.h"

// arduino-pico 5.5.0 dropped the TinyUSB HID class driver from the prebuilt
// libpico.a; the core only carries weak no-op stubs now, and a sketch pulls the
// real driver in by including this dummy header (the stock Mouse library does
// the same). Without it the link fails with undefined tud_hid_n_report /
// tud_hid_n_ready. Guarded by version so builds on 5.4.x, where the library
// doesn't exist, still work
#if ARDUINO_PICO_MAJOR > 5 || (ARDUINO_PICO_MAJOR == 5 && ARDUINO_PICO_MINOR >= 5)
#include <tusb-hid.h>
#endif

// Gaming-mouse-style report descriptor: like real high-DPI gaming mice, X/Y
// are declared as 16-bit relative axes. The header layout must keep
// HID_REPORT_ID at byte offset 6: the core rewrites the ID there when
// combining registered descriptors (USB.cpp setupDescHIDReport)
static const uint8_t mouse16Descriptor[] = {
  HID_USAGE_PAGE(HID_USAGE_PAGE_DESKTOP),
  HID_USAGE(HID_USAGE_DESKTOP_MOUSE),
  HID_COLLECTION(HID_COLLECTION_APPLICATION),
    HID_REPORT_ID(1)
    HID_USAGE(HID_USAGE_DESKTOP_POINTER),
    HID_COLLECTION(HID_COLLECTION_PHYSICAL),
      HID_USAGE_PAGE(HID_USAGE_PAGE_BUTTON),
      HID_USAGE_MIN(1),
      HID_USAGE_MAX(3),
      HID_LOGICAL_MIN(0),
      HID_LOGICAL_MAX(1),
      HID_REPORT_COUNT(3),
      HID_REPORT_SIZE(1),
      HID_INPUT(HID_DATA | HID_VARIABLE | HID_ABSOLUTE),
      HID_REPORT_COUNT(1),
      HID_REPORT_SIZE(5),
      HID_INPUT(HID_CONSTANT),
      HID_USAGE_PAGE(HID_USAGE_PAGE_DESKTOP),
      HID_USAGE(HID_USAGE_DESKTOP_X),
      HID_USAGE(HID_USAGE_DESKTOP_Y),
      HID_LOGICAL_MIN_N(-32767, 2),
      HID_LOGICAL_MAX_N(32767, 2),
      HID_REPORT_COUNT(2),
      HID_REPORT_SIZE(16),
      HID_INPUT(HID_DATA | HID_VARIABLE | HID_RELATIVE),
    HID_COLLECTION_END,
  HID_COLLECTION_END
};

typedef struct TU_ATTR_PACKED {
  uint8_t buttons;
  int16_t x;
  int16_t y;
} Mouse16Report;

void Mouse16Device::begin() {
  USB.disconnect();
  // same ordering/pidMask as the stock Mouse library, so the USB PID stays
  // what main.py's auto-detection expects
  _id = USB.registerHIDDevice(mouse16Descriptor, sizeof(mouse16Descriptor), 20, 0x0002);
  USB.connect();
}

void Mouse16Device::press(uint8_t b) {
  _buttons |= b;
  report(0, 0);
}

void Mouse16Device::release(uint8_t b) {
  _buttons &= ~b;
  report(0, 0);
}

void Mouse16Device::move(int x, int y) {
  report(x, y);
}

// mirrors the stock Mouse_::move(): same mutex/tud_task/HIDReady guard, one
// tud_hid_report call (~15-20µs), and the interface-level
// usb_hid_poll_interval override still applies
void Mouse16Device::report(int x, int y) {
  CoreMutex m(&USB.mutex);
  tud_task();
  if (USB.HIDReady()) {
    Mouse16Report r = { _buttons, (int16_t)constrain(x, -32767, 32767), (int16_t)constrain(y, -32767, 32767) };
    tud_hid_report(USB.findHIDReportID(_id), &r, sizeof(r));
  }
  tud_task();
}

// Busy-waits until the host's IN token has actually picked up the queued
// report — tud_hid_ready() flips back to true only when tud_task() processes
// the transfer-complete event, so the loop pumps it. Neither call touches the
// bus: USB is host-driven and the report was armed once, so polling here just
// observes the pickup with ~µs resolution. USB.mutex is the core's tud_task()
// reentrancy guard: the 1ms IRQ pump (USBClass::usbIRQ) try-enters it and
// skips while user code owns it, so pumping without the mutex would let the
// IRQ nest a tud_task() inside ours. Holding it doesn't delay detection — the
// completion event is posted by the USB hardware IRQ, which ignores the
// mutex; our loop just has to consume it. Returns false on timeout (host
// stopped polling: suspend, unplug — or report() skipped the send). The
// pico-sdk mutex is non-recursive, so this must never be called while
// USB.mutex is held, i.e. only after press()/move() returned.
bool Mouse16Device::waitDelivered(unsigned long timeoutUs) {
  CoreMutex m(&USB.mutex);
  unsigned long start = micros();
  while (micros() - start < timeoutUs) {
    tud_task();
    if (tud_hid_ready()) {
      return true;
    }
  }
  return false;
}

Mouse16Device Mouse16;
