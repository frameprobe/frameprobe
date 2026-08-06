#include "mouse16.h"

#include <USB.h>
#include "tusb.h"
#include "class/hid/hid_device.h"

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

Mouse16Device Mouse16;
