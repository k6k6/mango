# Scroller-deck integration test

The test starts an isolated headless Mango instance, keeps real windows open,
and exercises insertion, tabs, focus, resizing, changing the independent window
count, automatic backfill, manual splits, layout switching, overview and separate
state for tags and monitors. `focusdeck` coverage includes forward/reverse wraps,
master/floating/empty/single-member no-ops, filtering minimized and off-tag windows,
tab mode off, fullscreen, overview and monitor isolation. `focusstack` still wraps
through master windows. Close-focus checks keep real windows open while changing
focus history, then close through IPC, a keyboard binding or the application.
They cover the left neighbor, the first tab's right fallback without wrapping,
inactive tabs, saved manual split links, tab mode off, fullscreen, no masters,
a singleton/empty deck, filtered neighbors and unchanged fallback outside the
deck. Tag-focus checks keep windows open on two tags, select different active
members, and leave focus on a master before switching tags. They verify that the
active deck member survives tab-chain rebuilding and direction changes. With
`wtype`, they also interleave Super+1/2 and Super+h/l at 0, 3 and 9 ms intervals,
with animations off, vertical/horizontal tag animations on, and zero, one or two
masters; state is checked again after animations finish. It uses a private
runtime directory and configuration. Master-count checks promote an active tab
away from the deck's front through a real keybinding, relative changes and an
absolute increase. They cover unchanged order on decreases and no-ops, multiple
new masters, zero masters, master focus, tab mode off, a singleton deck, clamping,
and unchanged order in other layouts and overview. Exchange checks swap a master
with the first, middle and last deck member in both directions, verify that the
old master becomes the active deck member in the original tab slot, and keep
keyboard focus on the initiating window. They cover tag switching, tab mode off,
saved manual split links, a singleton deck, master-only swaps and the ordinary
Scroller layout. With `wtype`, continuous exchange key presses run at 0, 3 and 9 ms
intervals with animations off and on, checking immediate and settled state.

```sh
meson setup /tmp/mango-scroller-deck-build . -Dasan=true -Dbuildtype=debugoptimized
meson compile -C /tmp/mango-scroller-deck-build
python3 tests/scroller_deck.py /tmp/mango-scroller-deck-build
```

Required: `foot`, Python 3, the built `mango` / `mmsg`, and a GLES renderer that
supports software rendering. The test enables Mesa software rendering and
wlroots' headless backend.

Additional checks run when the tools are installed:

- `wtype`: send actual virtual keyboard events to the count, deck focus,
  exchange and close bindings, and Ctrl+D to close a terminal from inside its application.
  The fixture uses `binds` to match symbols because wtype provides its own keymap.
- `wayland-scanner`, `cc`, `pkg-config`, Wayland client development files, and
  `/usr/share/wlr-protocols/unstable/wlr-virtual-pointer-unstable-v1.xml`: compile
  `virtual_pointer.c` in the temporary directory, then test tab clicks and clicks
  after scrolling the deck out of view.
- `xterm`: insert and select an XWayland window in the automatic deck.
- `grim`: capture the initial layout and the deck after scrolling it out of view.

Logs, screenshots and JSON snapshots remain in the printed temporary directory.
The script fails on compositor crashes, incorrect window state or AddressSanitizer
errors. Leak detection is disabled for this behavior test.

The fixture explicitly destroys its virtual outputs before stopping Mango. The
original compositor also has an input-method relay use-after-free when shutdown
leaves multiple outputs for backend destruction; that separate cleanup issue is
outside these layout changes.
