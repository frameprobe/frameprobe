# Vulkan Color Switcher

### Installation on macOS

```bash
brew install vulkan-headers vulkan-loader molten-vk glfw cmake
```

## Building

```bash
cd color-switcher-vulkan/build
cmake ..
cmake --build .
```

## Running

```bash
./color-switcher-vulkan/build/bin/color-switcher
```

Left click toggles black/white, Esc quits.

Flags:

- `--present-mode immediate|mailbox|fifo|fifo-relaxed` — force a present mode (errors out if the surface doesn't support it) instead of the automatic IMMEDIATE → MAILBOX → FIFO_RELAXED → FIFO fallback.
- `--windowed` — run in an 800x600 window instead of fullscreen. For development only: windowed surfaces are always composited/vsynced, so don't use it for measurement runs.