#! /bin/sh
set -e

# https://docs.arduino.cc/arduino-cli/

# The rp2040:rp2040 core (earlephilhower/arduino-pico) lives in a third-party
# index, so it must be installed with the board manager URL on a fresh machine.
RP2040_INDEX_URL="https://github.com/earlephilhower/arduino-pico/releases/download/global/package_rp2040_index.json"

# Default: Waveshare RP2040-Zero (the frameprobe PCB module).
# For the old QT Py perfboard: FQBN=rp2040:rp2040:adafruit_qtpy ./flash_rp2040.sh
FQBN="${FQBN:-rp2040:rp2040:waveshare_rp2040_zero}"

REPO_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
BUILD_DIR="$REPO_DIR/build"
UF2="$BUILD_DIR/arduino.ino.uf2"

# How long to wait for the user to press BOOT, in seconds.
BOOTSEL_TIMEOUT="${BOOTSEL_TIMEOUT:-60}"

# How many times to retry the copy, once a second, before giving up.
COPY_RETRIES="${COPY_RETRIES:-15}"

# Mount point of the RP2040 mass-storage bootloader, or nothing if not mounted.
bootsel_drive() {
    for d in /Volumes/RPI-RP2 /media/*/RPI-RP2 /run/media/*/RPI-RP2 /mnt/RPI-RP2; do
        if [ -d "$d" ]; then
            printf '%s\n' "$d"
            return 0
        fi
    done
    return 1
}

# Instructions on stderr so that stdout stays free for the drive path.
prompt_bootsel() {
    cat >&2 <<EOF

Put the board into BOOTSEL mode by hand:

  unplug the board  ->  hold BOOT  ->  plug it back in  ->  release BOOT

(or, without unplugging: hold BOOT, tap RESET, release RESET, release BOOT)

Waiting up to ${BOOTSEL_TIMEOUT}s for the RPI-RP2 drive to appear
EOF
}

wait_for_bootsel() {
    i=0
    while [ "$i" -lt "$BOOTSEL_TIMEOUT" ]; do
        if drive=$(bootsel_drive); then
            printf '\n' >&2
            printf '%s\n' "$drive"
            return 0
        fi
        printf '.' >&2
        sleep 1
        i=$((i + 1))
    done
    printf '\n' >&2
    return 1
}

deploy_uf2() {
    drive="$1"
    echo "Copying arduino.ino.uf2 to $drive ..."
    i=0
    while :; do
        if err=$(cp "$UF2" "$drive/" 2>&1); then
            sync
            break
        fi
        # The board reboots the instant the last block lands, so the drive can
        # disappear mid-copy and cp then reports an I/O error even though the
        # flash succeeded.
        if [ ! -d "$drive" ]; then
            break
        fi
        # Still mounted, so the copy really did fail. Usually because the drive
        # has only just appeared and is not writable yet ("Permission denied"),
        # which clears within a few seconds -- so retry before giving up.
        i=$((i + 1))
        if [ "$i" -ge "$COPY_RETRIES" ]; then
            if [ -n "$err" ]; then
                printf '%s\n' "$err" >&2
            fi
            echo "error: copying the firmware to $drive failed" >&2
            return 1
        fi
        sleep 1
    done
    echo "Flashed. The board reboots into the sketch now."
}

if ! arduino-cli core list | grep -q '^rp2040:rp2040'; then
    arduino-cli core update-index --additional-urls "$RP2040_INDEX_URL"
    arduino-cli core install rp2040:rp2040 --additional-urls "$RP2040_INDEX_URL"
fi

if ! arduino-cli lib list "Adafruit NeoPixel" | grep -q 'Adafruit NeoPixel'; then
    arduino-cli lib install "Adafruit NeoPixel"
fi

arduino-cli compile --fqbn "$FQBN" --output-dir "$BUILD_DIR" arduino

# A board sitting in BOOTSEL has no serial port, so arduino-cli cannot drive it.
# Copy straight to the drive instead.
if drive=$(bootsel_drive); then
    echo "Board is already in BOOTSEL mode ($drive)."
    deploy_uf2 "$drive"
    exit 0
fi

# Port: first CLI arg, else first matching device (macOS: cu.usbmodem*, Linux: ttyACM*)
PORT="${1:-$(ls /dev/cu.usbmodem* /dev/ttyACM* 2>/dev/null | head -n 1)}"

if [ -n "$PORT" ]; then
    # arduino-cli reboots the board into BOOTSEL by opening the port at 1200
    # baud. That only works if the firmware already on the board implements
    # the touch reset -- a factory board (MicroPython, Pico SDK demo) does not,
    # and neither does a sketch that hung hard enough to drop off USB.
    if arduino-cli upload -p "$PORT" --fqbn "$FQBN" --input-dir "$BUILD_DIR" arduino; then
        exit 0
    fi
    echo "" >&2
    echo "Automatic upload failed: the board did not reset into BOOTSEL." >&2
else
    echo "No serial port found (/dev/cu.usbmodem* or /dev/ttyACM*)." >&2
fi

prompt_bootsel
if drive=$(wait_for_bootsel); then
    deploy_uf2 "$drive"
else
    echo "error: RPI-RP2 drive did not appear within ${BOOTSEL_TIMEOUT}s" >&2
    exit 1
fi
