#!/usr/bin/env python3
"""Exercise scroller-deck with real foot windows in an isolated headless Mango.

Usage: python3 tests/scroller_deck.py /path/to/meson-build
Requires foot, a software GLES renderer, and the built mango/mmsg binaries.
Logs and state snapshots are kept in the printed temporary directory.
"""

import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import time


class Session:
    def __init__(self, build):
        self.build = Path(build).resolve()
        self.root = Path(tempfile.mkdtemp(prefix="mango-scroller-deck-test-"))
        self.runtime = self.root / "runtime"
        self.runtime.mkdir(mode=0o700)
        self.env = os.environ.copy()
        for key in ("WAYLAND_DISPLAY", "DISPLAY", "DBUS_SESSION_BUS_ADDRESS",
                    "MANGO_INSTANCE_SIGNATURE"):
            self.env.pop(key, None)
        self.env.update(
            XDG_RUNTIME_DIR=str(self.runtime),
            XDG_CONFIG_HOME=str(self.root / "config"),
            WLR_BACKENDS="headless", WLR_HEADLESS_OUTPUTS="1",
            WLR_RENDERER="gles2", WLR_RENDERER_ALLOW_SOFTWARE="1",
            LIBGL_ALWAYS_SOFTWARE="1", ASAN_OPTIONS="detect_leaks=0:abort_on_error=1",
        )
        self.config = self.root / "config.conf"
        self.config.write_text("""animations=0
layer_animations=0
blur=0
shadows=0
sloppy_focus=0
warp_cursor=0
focus_cross_tag=0
focus_cross_monitor=0
default_scroller_master_count=2
scroller_default_proportion=0.45
scroller_ignore_proportion_single=1
scroller_proportion_preset=0.5,0.8,1.0
deck_tab_mode=1
tag_num=4
tag_rule=id:1,layout_name:scroller-deck
tag_rule=id:2,layout_name:scroller-deck,scroller_master_count:0
# wtype supplies its own keymap, so match symbols in this fixture.
binds=SUPER,bracketright,inc_scroller_master_count,+1
binds=SUPER,bracketleft,inc_scroller_master_count,-1
binds=SUPER,j,focusdeck,next
binds=SUPER,k,focusdeck,prev
binds=SUPER,h,focusdir,left
binds=SUPER,l,focusdir,right
binds=SUPER,1,view,1,0
binds=SUPER,2,view,2,0
binds=SUPER,q,killclient
""")
        subprocess.run([str(self.build / "mango"), "-p", "-c", str(self.config)],
                       env=self.env, check=True, capture_output=True, timeout=5)
        self.log = (self.root / "mango.log").open("w")
        self.process = subprocess.Popen(
            [str(self.build / "mango"), "-c", str(self.config)],
            env=self.env, stdout=self.log, stderr=self.log,
        )
        self.windows = []
        try:
            self.env["MANGO_INSTANCE_SIGNATURE"] = str(
                self.runtime / f"mango-{self.process.pid}.sock")
            self.wait(lambda: Path(self.env["MANGO_INSTANCE_SIGNATURE"]).exists(),
                      "IPC socket")
            self.wait(lambda: self.get("all-monitors").get("monitors"), "output")
            displays = list(self.runtime.glob("wayland-*"))
            self.env["WAYLAND_DISPLAY"] = next(
                path.name for path in displays if not path.name.endswith(".lock"))
            self.monitor = self.get("all-monitors")["monitors"][0]["name"]
            self.pointer_helper = None
            protocol = Path("/usr/share/wlr-protocols/unstable/wlr-virtual-pointer-unstable-v1.xml")
            if protocol.exists() and shutil.which("wayland-scanner"):
                header = self.root / "virtual-pointer-protocol.h"
                code = self.root / "virtual-pointer-protocol.c"
                subprocess.run(["wayland-scanner", "client-header", str(protocol), str(header)], check=True)
                subprocess.run(["wayland-scanner", "private-code", str(protocol), str(code)], check=True)
                flags = subprocess.check_output(
                    ["pkg-config", "--cflags", "--libs", "wayland-client"], text=True).split()
                self.pointer_helper = self.root / "virtual-pointer"
                subprocess.run(["cc", "-I", str(self.root),
                                str(Path(__file__).with_name("virtual_pointer.c")),
                                str(code), "-o", str(self.pointer_helper), *flags], check=True)
            print(f"Artifacts: {self.root}", flush=True)
        except BaseException:
            if self.process.poll() is None:
                self.process.terminate()
                self.process.wait(timeout=5)
            self.log.close()
            raise

    def pointer(self, x, y, click=False):
        monitors = self.get("all-monitors")["monitors"]
        width = max(m["x"] + m["width"] for m in monitors)
        height = max(m["y"] + m["height"] for m in monitors)
        command = [str(self.pointer_helper), str(int(x)), str(int(y)),
                   str(width), str(height)]
        if click:
            command.append("click")
        subprocess.run(command, env=self.env, check=True, timeout=5)

    def capture(self, name):
        if shutil.which("grim"):
            subprocess.run(["grim", "-o", self.monitor, str(self.root / f"{name}.png")],
                           env=self.env, check=True, capture_output=True, timeout=5)

    def wait(self, predicate, description, timeout=8):
        until = time.monotonic() + timeout
        while time.monotonic() < until:
            if self.process.poll() is not None:
                raise AssertionError(f"Mango exited ({self.process.returncode}): "
                                     f"{self.root / 'mango.log'}")
            if predicate():
                return
            time.sleep(0.03)
        raise AssertionError(f"Timed out waiting for {description}")

    def call(self, *args):
        result = subprocess.run([str(self.build / "mmsg"), *args], env=self.env,
                                capture_output=True, text=True, timeout=5)
        if result.returncode:
            raise AssertionError(f"mmsg {args}: {result.stderr} {result.stdout}")
        return json.loads(result.stdout) if result.stdout.strip() else {}

    def get(self, *args):
        return self.call("get", *args)

    def dispatch(self, command, client=None):
        args = ["dispatch", command]
        if client is not None:
            args.append(f"client,{client}")
        result = self.call(*args)
        if isinstance(result, dict) and "error" in result:
            raise AssertionError(f"{command}: {result}")
        # Read after the dispatch to observe the compositor's arranged state.
        return self.clients()

    def clients(self):
        return self.get("all-clients")["clients"]

    def by_name(self):
        return {c["title"]: c for c in self.clients()}

    def open(self, name):
        log = (self.root / f"foot-{name}.log").open("w")
        proc = subprocess.Popen(
            ["foot", "-c", "/dev/null", "-T", name, "-a", f"sd-{name}",
             "sh", "-c", "printf 'scroller-deck integration window\\n'; exec cat"],
            env=self.env, stdout=log, stderr=log,
        )
        self.windows.append((proc, log))
        self.wait(lambda: name in self.by_name(), f"window {name}")
        self.wait(lambda: self.get("focusing-client").get("title") == name,
                  f"focus {name}")
        return self.by_name()[name]["id"]

    def focus(self, name):
        self.dispatch("focusid", self.by_name()[name]["id"])
        assert self.get("focusing-client")["title"] == name

    def expect_focus(self, command, name, client=None):
        self.dispatch(command, client)
        actual = self.get("focusing-client").get("title")
        assert actual == name, (command, "focus", actual, name)

    def check(self, label, order, masters, deck):
        clients = [c for c in self.clients() if c["monitor"] == self.monitor
                   and c["tags"] == [1] and not c["is_minimized"]
                   and not c["is_floating"]]
        actual = [c["title"] for c in clients]
        assert actual == order, (label, "order", actual, order)
        actual_masters = [c["title"] for c in clients if c["is_master"]]
        assert actual_masters == masters, (label, "masters", actual_masters, masters)
        tabs = [c for c in clients if c["title"] in deck]
        if len(tabs) >= 2:
            assert len({(c["x"], c["y"], c["width"], c["height"])
                        for c in tabs}) == 1, (label, "deck geometry", tabs)
            assert sum(c["is_tab_focus"] for c in tabs) == 1, (label, tabs)
            assert sum(c["is_tab_hidden"] for c in tabs) == len(tabs) - 1
        assert all(not c["is_tab_hidden"] for c in clients
                   if c["title"] in masters or len(deck) < 2), (label, clients)
        if len(tabs) == 1 and masters:
            master = next(c for c in clients if c["title"] == masters[0])
            assert tabs[0]["y"] == master["y"], (label, "singleton tab strip")
        assert all(c["width"] > 0 and c["height"] > 0 for c in clients)
        (self.root / f"{label}.json").write_text(json.dumps(clients, indent=2))
        print(f"PASS {label}: {' '.join(masters)} [{' '.join(deck)}]", flush=True)

    def close(self):
        for proc, log in self.windows:
            if proc.poll() is None:
                proc.terminate()
            try:
                proc.wait(timeout=3)
            except subprocess.TimeoutExpired:
                proc.kill()
                proc.wait()
            log.close()
        if self.process.poll() is None:
            for client in self.clients():
                self.dispatch("killclient", client["id"])
            self.wait(lambda: not self.clients(), "test windows to close")
            # Release the outputs created by this fixture while Mango is live.
            # Original Mango has an IM-relay UAF when multiple outputs are
            # left for backend destruction during compositor shutdown.
            if len(self.get("all-monitors")["monitors"]) > 1:
                self.dispatch("destroy_all_virtual_output")
            self.process.terminate()
        try:
            self.process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            self.process.kill()
            self.process.wait()
        self.log.close()
        log = (self.root / "mango.log").read_text()
        assert "ERROR: AddressSanitizer" not in log, log
        assert "AddressSanitizer:DEADLYSIGNAL" not in log, log


def exercise(s):
    s.expect_focus("focusdeck,next", None)
    s.expect_focus("focusdeck,prev", None)
    for name in "ABCD":
        s.open(name)
    s.check("initial", list("ABCD"), list("AB"), list("CD"))
    s.capture("initial")
    if shutil.which("wtype"):
        subprocess.run(["wtype", "-M", "logo", "-k", "bracketright", "-m", "logo"],
                       env=s.env, check=True, timeout=5)
        s.wait(lambda: s.get("monitor", s.monitor)["tags"][0]["scroller_master_count"] == 3,
               "increment keybinding")
        subprocess.run(["wtype", "-M", "logo", "-k", "bracketleft", "-m", "logo"],
                       env=s.env, check=True, timeout=5)
        s.wait(lambda: s.get("monitor", s.monitor)["tags"][0]["scroller_master_count"] == 2,
               "decrement keybinding")
        s.check("keyboard-count", list("ABCD"), list("AB"), list("CD"))

    s.focus("A")
    s.open("E")
    s.check("insert-after-master", list("AEBCD"), list("AE"), list("BCD"))
    s.focus("C")
    s.open("F")
    s.check("insert-after-tab", list("AEBCFD"), list("AE"), list("BCFD"))

    s.dispatch("inc_scroller_master_count,+1")
    s.check("increment", list("AEBCFD"), list("AEB"), list("CFD"))
    assert s.get("focusing-client")["title"] == "F"
    s.dispatch("inc_scroller_master_count,-1")
    s.check("decrement", list("AEBCFD"), list("AE"), list("BCFD"))
    s.dispatch("set_scroller_master_count,0")
    s.check("all-tabs", list("AEBCFD"), [], list("AEBCFD"))
    s.focus("D")
    s.expect_focus("focusdeck,next", "A")
    s.expect_focus("focusdeck,prev", "D")
    s.dispatch("set_scroller_master_count,99")
    s.check("all-independent", list("AEBCFD"), list("AEBCFD"), [])
    s.expect_focus("focusdeck,next", "D")
    s.expect_focus("focusdeck,prev", "D")
    s.dispatch("set_scroller_master_count,-1")
    s.check("negative-clamped", list("AEBCFD"), [], list("AEBCFD"))
    s.dispatch("inc_scroller_master_count,2147483647")
    s.check("increment-clamped", list("AEBCFD"), list("AEBCFD"), [])
    s.dispatch("set_scroller_master_count,2")

    s.focus("C")
    s.dispatch("set_proportion,0.5")
    width = s.by_name()["C"]["width"]
    s.focus("D")
    assert s.by_name()["D"]["width"] == width
    s.dispatch("switch_proportion_preset")
    wider = s.by_name()["D"]["width"]
    assert wider > width, (width, wider)
    s.focus("F")
    assert s.by_name()["F"]["width"] == wider
    s.check("shared-width", list("AEBCFD"), list("AE"), list("BCFD"))
    if s.pointer_helper:
        s.focus("D")
        tab = s.by_name()["D"]
        s.pointer(tab["x"] + tab["width"] / 8, tab["y"] - 16, click=True)
        assert s.get("focusing-client")["title"] == "B"
        s.check("mouse-select-tab", list("AEBCFD"), list("AE"), list("BCFD"))
        s.dispatch("set_scroller_master_count,3")
        s.focus("D")
        old_tab = s.by_name()["D"]
        s.focus("A")
        s.capture("deck-offscreen")
        s.pointer(old_tab["x"] + old_tab["width"] / 6, old_tab["y"] - 16, click=True)
        assert s.get("focusing-client")["is_master"], "off-screen tab retained a clickable strip"
        s.dispatch("set_scroller_master_count,2")
        s.focus("F")
    s.dispatch("resizewin,-100,0")
    assert s.by_name()["F"]["width"] < wider
    s.focus("B")
    resized_width = s.by_name()["B"]["width"]
    s.focus("C")
    assert s.by_name()["C"]["width"] == resized_width

    s.focus("D")
    s.focus("E")
    s.dispatch("focusdir,right")
    assert s.get("focusing-client")["title"] == "D"
    s.dispatch("focusdir,left")
    assert s.get("focusing-client")["title"] == "E"
    s.focus("C")
    s.dispatch("focusstack,next")
    assert s.get("focusing-client")["title"] == "F"
    s.check("focus-navigation", list("AEBCFD"), list("AE"), list("BCFD"))

    s.focus("D")
    deck_width = s.by_name()["D"]["width"]
    for name in "BCFDBCFD":
        s.expect_focus("focusdeck,next", name)
    for name in "FCBDFCBD":
        s.expect_focus("focusdeck,prev", name)
    assert all(s.by_name()[name]["width"] == deck_width for name in "BCFD")
    s.check("focusdeck-wrap", list("AEBCFD"), list("AE"), list("BCFD"))
    # The existing global action must keep crossing the master/deck boundary.
    s.expect_focus("focusstack,next", "A")
    s.focus("B")
    s.expect_focus("focusstack,prev", "E")
    for master in "AE":
        s.focus(master)
        s.expect_focus("focusdeck,next", master)
        s.expect_focus("focusdeck,prev", master)
    # IPC's explicit client is the navigation anchor, not the focused window.
    s.focus("C")
    s.expect_focus("focusdeck,next", "B", s.by_name()["D"]["id"])
    s.expect_focus("focusdeck,prev", "D")
    if shutil.which("wtype"):
        for key, name in (("j", "B"), ("k", "D")):
            subprocess.run(["wtype", "-M", "logo", "-k", key, "-m", "logo"],
                           env=s.env, check=True, timeout=5)
            s.wait(lambda: s.get("focusing-client").get("title") == name,
                   f"focusdeck keyboard focus {name}")
        s.check("keyboard-focusdeck-wrap", list("AEBCFD"), list("AE"), list("BCFD"))

    s.dispatch("togglefloating", s.by_name()["F"]["id"])
    s.focus("F")
    s.expect_focus("focusdeck,next", "F")
    s.expect_focus("focusdeck,prev", "F")
    s.focus("C")
    s.expect_focus("focusdeck,next", "D")
    s.expect_focus("focusdeck,prev", "C")
    s.check("focusdeck-skips-floating", list("AEBCD"), list("AE"), list("BCD"))
    s.dispatch("togglefloating", s.by_name()["F"]["id"])

    s.dispatch("togglefloating", s.by_name()["E"]["id"])
    s.check("floating-backfill", list("ABCFD"), list("AB"), list("CFD"))
    s.dispatch("togglefloating", s.by_name()["E"]["id"])
    s.check("floating-restore", list("AEBCFD"), list("AE"), list("BCFD"))
    s.dispatch("minimized", s.by_name()["E"]["id"])
    s.check("minimize-backfill", list("ABCFD"), list("AB"), list("CFD"))
    s.focus("D")
    s.expect_focus("focusdeck,next", "C")
    s.expect_focus("focusdeck,prev", "D")
    s.dispatch("restore_minimized", s.by_name()["E"]["id"])
    # Mango's existing restore_minimized appends the restored client to the end.
    s.check("minimize-restore", list("ABCFDE"), list("AB"), list("CFDE"))
    for _ in range(4):
        s.dispatch("exchange_stack_client,prev", s.by_name()["E"]["id"])
    s.check("exchange-across-boundary", list("AEBCFD"), list("AE"), list("BCFD"))

    s.focus("E")
    s.dispatch("scroller_stack,left")
    s.check("manual-split", list("AEBCFD"), list("AE"), list("BCFD"))
    clients = s.by_name()
    assert clients["A"]["x"] == clients["E"]["x"]
    assert clients["A"]["y"] < clients["E"]["y"]
    assert clients["A"]["height"] < clients["B"]["height"]
    s.focus("A")
    s.open("X")
    s.check("insert-in-manual-split", list("AXEBCFD"), list("AX"), list("EBCFD"))
    clients = s.by_name()
    assert clients["A"]["height"] == clients["X"]["height"]
    s.dispatch("killclient", clients["X"]["id"])
    s.wait(lambda: "X" not in s.by_name(), "closed inserted window")
    s.check("restore-manual-split", list("AEBCFD"), list("AE"), list("BCFD"))
    clients = s.by_name()
    assert clients["A"]["x"] == clients["E"]["x"]
    assert clients["A"]["y"] < clients["E"]["y"]
    s.dispatch("set_scroller_master_count,1")
    s.check("split-crosses-boundary", list("AEBCFD"), ["A"], list("EBCFD"))
    s.dispatch("setlayout,scroller")
    s.focus("D")
    s.expect_focus("focusdeck,next", "D")
    s.expect_focus("focusdeck,prev", "D")
    clients = s.by_name()
    assert clients["A"]["x"] == clients["E"]["x"]
    assert clients["A"]["y"] < clients["E"]["y"]
    assert all(not c["is_tab_hidden"] for c in clients.values())
    s.dispatch("setlayout,scroller-deck")
    s.check("return-from-scroller", list("AEBCFD"), ["A"], list("EBCFD"))
    s.dispatch("set_scroller_master_count,2")
    s.dispatch("scroller_stack,right", s.by_name()["E"]["id"])
    s.check("manual-unstack", list("AEBCFD"), list("AE"), list("BCFD"))
    clients = s.by_name()
    assert clients["A"]["x"] != clients["E"]["x"]

    s.dispatch("set_scroller_master_count,5")
    s.check("single-deck-member", list("AEBCFD"), list("AEBCF"), ["D"])
    s.focus("D")
    s.expect_focus("focusdeck,next", "D")
    s.expect_focus("focusdeck,prev", "D")
    s.dispatch("set_scroller_master_count,2")
    s.dispatch("view,2")
    s.expect_focus("focusdeck,next", None)
    s.expect_focus("focusdeck,prev", None)
    s.dispatch("setlayout,scroller-deck")
    tags = s.get("monitor", s.monitor)["tags"]
    assert tags[0]["scroller_master_count"] == 2
    assert tags[1]["scroller_master_count"] == 0
    s.dispatch("set_scroller_master_count,1")
    s.dispatch("view,1")
    s.check("per-tag-count", list("AEBCFD"), list("AE"), list("BCFD"))
    tags = s.get("monitor", s.monitor)["tags"]
    assert tags[0]["scroller_master_count"] == 2
    assert tags[1]["scroller_master_count"] == 1

    s.dispatch("setlayout,deck")
    clients = s.by_name()
    assert sum(c["is_master"] for c in clients.values()) == 1
    s.dispatch("setlayout,scroller-deck")
    s.check("deck-count-independent", list("AEBCFD"), list("AE"), list("BCFD"))
    s.focus("C")
    s.dispatch("togglefullscreen")
    assert s.by_name()["C"]["is_fullscreen"]
    s.expect_focus("focusdeck,prev", "B")
    s.expect_focus("focusdeck,prev", "D")
    s.expect_focus("focusdeck,next", "B")
    s.expect_focus("focusdeck,next", "C")
    s.dispatch("togglefullscreen")
    s.check("fullscreen-restore", list("AEBCFD"), list("AE"), list("BCFD"))

    s.focus("E")
    s.dispatch("killclient")
    s.wait(lambda: "E" not in s.by_name(), "closed master")
    s.check("close-backfill", list("ABCFD"), list("AB"), list("CFD"))
    s.dispatch("set_scroller_master_count,0")
    s.dispatch("reload_config")
    s.check("reload-count", list("ABCFD"), list("AB"), list("CFD"))
    assert s.get("tag", s.monitor, "1")["scroller_master_count"] == 2
    s.dispatch("tagsilent,2", s.by_name()["A"]["id"])
    s.check("move-tag-backfill", list("BCFD"), list("BC"), list("FD"))
    s.focus("D")
    s.expect_focus("focusdeck,next", "F")
    s.expect_focus("focusdeck,prev", "D")
    # An explicit off-tag client must not pull focus away from this view.
    s.expect_focus("focusdeck,next", "D", s.by_name()["A"]["id"])
    s.dispatch("tagsilent,1", s.by_name()["A"]["id"])
    s.check("move-tag-restore", list("ABCFD"), list("AB"), list("CFD"))
    if shutil.which("xterm"):
        s.focus("C")
        s.dispatch("spawn_shell,xterm -title XW -name sd-XW -e cat")
        s.wait(lambda: "XW" in s.by_name(), "XWayland window")
        s.wait(lambda: s.get("focusing-client").get("title") == "XW", "XWayland focus")
        assert s.by_name()["XW"]["is_xwayland"]
        s.check("xwayland-tab", ["A", "B", "C", "XW", "F", "D"], list("AB"), ["C", "XW", "F", "D"])
        s.expect_focus("focusdeck,prev", "C")
        s.expect_focus("focusdeck,next", "XW")
        s.expect_focus("focusdeck,next", "F")
        s.expect_focus("focusdeck,prev", "XW")
        s.dispatch("killclient")
        s.wait(lambda: "XW" not in s.by_name(), "closed XWayland window")
        assert s.get("focusing-client").get("title") == "C"
        print("PASS close-xwayland-left-neighbor", flush=True)

    s.dispatch("enteroverview")
    overview_focus = s.get("focusing-client").get("title")
    s.expect_focus("focusdeck,next", overview_focus)
    s.expect_focus("focusdeck,prev", overview_focus)
    s.dispatch("leaveoverview")
    s.check("overview-return", list("ABCFD"), list("AB"), list("CFD"))
    s.dispatch("setoption,deck_tab_mode,0")
    clients = s.by_name()
    assert all(not c["is_tab_hidden"] and not c["is_tab_focus"]
               for c in clients.values())
    assert len({(clients[n]["x"], clients[n]["y"], clients[n]["width"], clients[n]["height"])
                for n in "CFD"}) == 1
    assert clients["C"]["y"] == clients["A"]["y"]
    s.focus("D")
    for name in "CFD":
        s.expect_focus("focusdeck,next", name)
    for name in "FCD":
        s.expect_focus("focusdeck,prev", name)
    print("PASS focusdeck-tab-mode-off", flush=True)
    s.dispatch("setoption,deck_tab_mode,1")
    s.check("tab-mode-reenabled", list("ABCFD"), list("AB"), list("CFD"))
    s.dispatch("setoption,circle_layout,scroller-deck,scroller")
    s.dispatch("switch_layout")
    assert s.get("monitor", s.monitor)["layout_symbol"] == "S"
    s.dispatch("switch_layout")
    s.check("cycle-layout", list("ABCFD"), list("AB"), list("CFD"))

    first_monitor = s.monitor
    s.dispatch("create_virtual_output,SD-SECOND")
    s.dispatch("focusmon,SD-SECOND")
    s.monitor = "SD-SECOND"
    s.dispatch("setlayout,scroller-deck")
    assert s.get("monitor", s.monitor)["tags"][0]["scroller_master_count"] == 2
    s.dispatch("set_scroller_master_count,0")
    for name in "GH":
        s.open(name)
    s.check("second-monitor", list("GH"), [], list("GH"))
    s.expect_focus("focusdeck,next", "G")
    s.expect_focus("focusdeck,prev", "H")
    s.dispatch(f"focusmon,{first_monitor}")
    s.monitor = first_monitor
    s.focus("D")
    s.expect_focus("focusdeck,next", "C")
    s.expect_focus("focusdeck,prev", "D")
    s.check("focusdeck-monitor-isolation", list("ABCFD"), list("AB"), list("CFD"))
    s.check("first-monitor-preserved", list("ABCFD"), list("AB"), list("CFD"))
    assert s.get("monitor", s.monitor)["tags"][0]["scroller_master_count"] == 2
    assert s.get("monitor", "SD-SECOND")["tags"][0]["scroller_master_count"] == 0


def exercise_close_focus(s):
    def close(label, name, expected, method="ipc"):
        snapshot = {"before": s.clients(),
                    "focus_before": s.get("focusing-client").get("title")}
        if method != "ipc" and shutil.which("wtype"):
            assert snapshot["focus_before"] == name
            # Ctrl+D makes the terminal's cat exit, closing from inside the app.
            modifier, key = ("ctrl", "d") if method == "app" else ("logo", "q")
            subprocess.run(["wtype", "-M", modifier, "-k", key, "-m", modifier],
                           env=s.env, check=True, timeout=5)
        else:
            method = "ipc"
            s.dispatch("killclient", s.by_name()[name]["id"])
        s.wait(lambda: name not in s.by_name(), f"{label}: {name} to close")
        actual = s.get("focusing-client").get("title")
        snapshot.update(after=s.clients(), focus_after=actual, expected=expected,
                        method=method)
        (s.root / f"{label}.json").write_text(json.dumps(snapshot, indent=2))
        assert actual == expected, (label, "focus", actual, expected)
        print(f"PASS {label}: closed {name}, focused {actual} ({method})", flush=True)

    def restore(name, left):
        s.focus(left)
        s.open(name)

    for name in "ABCDEF":
        s.open(name)
    s.check("close-initial", list("ABCDEF"), list("AB"), list("CDEF"))
    s.focus("E")
    s.focus("D")
    close("close-middle-prefers-left-over-history", "D", "C", "keyboard")
    restore("D", "C")
    s.focus("A")
    s.focus("F")
    close("close-last-stays-in-deck", "F", "E", "app")
    restore("F", "E")
    s.focus("F")
    s.focus("C")
    close("close-first-falls-right-without-wrapping", "C", "D")
    restore("C", "B")
    s.focus("C")
    s.focus("F")
    close("close-inactive-tab-keeps-focus", "D", "F")
    restore("D", "C")

    s.dispatch("setoption,deck_tab_mode,0")
    s.focus("F")
    s.focus("D")
    close("close-without-tab-links", "D", "C")
    restore("D", "C")
    s.dispatch("setoption,deck_tab_mode,1")
    s.focus("E")
    s.focus("D")
    s.dispatch("togglefullscreen")
    assert s.by_name()["D"]["is_fullscreen"]
    close("close-fullscreen-deck", "D", "C")
    restore("D", "C")

    # Saved Scroller split links must not override the automatic deck order.
    s.dispatch("setlayout,scroller")
    s.focus("E")
    s.dispatch("scroller_stack,left")
    clients = s.by_name()
    assert clients["D"]["x"] == clients["E"]["x"]
    assert clients["D"]["y"] < clients["E"]["y"]
    s.dispatch("setlayout,scroller-deck")
    s.focus("E")
    s.focus("D")
    close("close-ignores-saved-manual-split", "D", "C")
    restore("D", "C")
    s.check("close-restored-order", list("ABCDEF"), list("AB"), list("CDEF"))

    restore("G", "F")
    s.dispatch("minimized", s.by_name()["D"]["id"])
    s.dispatch("togglefloating", s.by_name()["E"]["id"])
    s.dispatch("tagsilent,2", s.by_name()["F"]["id"])
    first_monitor = s.monitor
    s.dispatch("create_virtual_output,SD-CLOSE")
    s.dispatch("focusmon,SD-CLOSE")
    s.open("H")
    s.dispatch(f"focusmon,{first_monitor}")
    s.focus("A")
    s.focus("G")
    close("close-skips-minimized-floating-offtag-other-monitor", "G", "C")
    close("close-on-other-monitor-keeps-focus", "H", "C")
    close("close-on-other-tag-keeps-focus", "F", "C")
    s.focus("E")
    close("close-floating-keeps-existing-fallback", "E", "C")
    s.dispatch("restore_minimized", s.by_name()["D"]["id"])
    s.check("close-filtered-restored", list("ABCD"), list("AB"), list("CD"))
    s.focus("C")
    s.focus("A")
    close("close-master-keeps-history-fallback", "A", "C")
    s.check("close-master-backfills", list("BCD"), list("BC"), ["D"])
    s.focus("B")
    s.focus("D")
    close("close-only-deck-member-keeps-fallback", "D", "B")

    s.dispatch("set_scroller_master_count,0")
    restore("D", "C")
    s.open("E")
    s.focus("D")
    close("close-all-deck-prefers-left", "D", "C")
    s.focus("E")
    s.focus("B")
    close("close-all-deck-first-falls-right", "B", "C")
    s.focus("E")
    close("close-two-deck-members", "E", "C")
    close("close-final-window", "C", None)

    s.dispatch("setlayout,scroller")
    for name in "ABCD":
        s.open(name)
    s.focus("C")
    close("close-ordinary-scroller-keeps-history", "C", "D")
    restore("C", "B")
    s.dispatch("setlayout,scroller-deck")
    s.dispatch("enteroverview")
    s.focus("D")
    s.focus("C")
    close("close-overview-keeps-history", "C", "D")
    s.dispatch("leaveoverview")


def exercise_tag_focus(s):
    # Keep both tags' real windows open throughout tag and direction changes.
    s.dispatch("set_scroller_master_count,1")
    for name in "ABCD":
        s.open(name)
    s.dispatch("view,2")
    s.dispatch("set_scroller_master_count,1")
    for name in "WXYZ":
        s.open(name)

    base_config = s.config.read_text()
    snapshots = []

    def expect_state(label, tag, focus, active):
        clients = s.clients()
        tabs = [c for c in clients if c["tags"] == [tag]
                and not c["is_master"] and not c["is_floating"]
                and not c["is_minimized"]]
        actual_focus = s.get("focusing-client").get("title")
        actual_active = [c["title"] for c in tabs if c["is_tab_focus"]]
        snapshots.append({"label": label, "focus": actual_focus,
                          "active": actual_active, "clients": clients})
        (s.root / "tag-focus.json").write_text(json.dumps(snapshots, indent=2))
        assert actual_focus == focus, (label, "focus", actual_focus, focus)
        assert actual_active == [active], (label, "active", actual_active, active)
        assert [c["title"] for c in tabs if not c["is_tab_hidden"]] == [active], (
            label, "visible deck", tabs)

    def keyboard(keys, delay):
        command = ["wtype", "-M", "logo"]
        for key in keys:
            command.extend(["-k", key])
            if delay:
                command.extend(["-s", str(delay)])
        command.extend(["-m", "logo"])
        subprocess.run(command, env=s.env, check=True, timeout=10)

    for animations, direction, masters in (
            (0, 0, 1), (1, 0, 1), (1, 1, 1), (1, 0, 2), (1, 0, 0)):
        label = f"tag-focus-anim{animations}-dir{direction}-masters{masters}"
        s.config.write_text(base_config + f"""
animations={animations}
tag_animation_direction={direction}
animation_duration_move=200
animation_duration_tag=150
""")
        s.dispatch("reload_config")
        s.dispatch("view,2")
        s.dispatch(f"set_scroller_master_count,{masters}")
        s.focus("Z")
        if masters:
            s.focus("W")
        s.dispatch("view,1")
        s.dispatch(f"set_scroller_master_count,{masters}")
        s.focus("D")
        if masters:
            s.focus("A")
        first_focus, second_focus = ("A", "W") if masters else ("D", "Z")
        expect_state(label + "-initial", 1, first_focus, "D")

        # Rebuilding a tab chain while a master has focus used to choose B/X.
        s.dispatch("view,2")
        expect_state(label + "-restore-tag2", 2, second_focus, "Z")
        s.dispatch("view,1")
        expect_state(label + "-restore-tag1", 1, first_focus, "D")
        for _ in range(masters + 1):
            s.dispatch("focusdir,right")
        expect_state(label + "-enter-deck", 1, "D", "D")
        for _ in range(masters + 1):
            s.dispatch("focusdir,left")
        expect_state(label + "-leave-deck", 1, first_focus, "D")

        if shutil.which("wtype"):
            # Zero delay covers a burst; small delays let frames and tag
            # animations run between actual key presses, still within 150 ms.
            directions = ["h", "h", "l", "l", "l", "h", "h"]
            cycle = ["2", *directions, "1", *directions]
            for delay in (0, 3, 9):
                keyboard(cycle * 8, delay)
                expect_state(label + f"-burst{delay}-tag1", 1, first_focus, "D")
                keyboard(["2", *directions], delay)
                expect_state(label + f"-burst{delay}-tag2", 2, second_focus, "Z")
                keyboard(["1", *directions], delay)
                expect_state(label + f"-return{delay}", 1, first_focus, "D")
                # Let the final animation complete without changing focus.
                time.sleep(0.25)
                expect_state(label + f"-settled{delay}", 1, first_focus, "D")
        else:
            print("SKIP rapid tag-focus keyboard checks: wtype unavailable", flush=True)
        print(f"PASS {label}: tag1 [D], tag2 [Z]", flush=True)


def main():
    if len(sys.argv) != 2 or not shutil.which("foot"):
        raise SystemExit(__doc__)
    for run in (exercise, exercise_close_focus, exercise_tag_focus):
        session = None
        try:
            session = Session(sys.argv[1])
            run(session)
        finally:
            if session:
                session.close()
    print("All scroller-deck integration checks passed.", flush=True)


if __name__ == "__main__":
    main()
