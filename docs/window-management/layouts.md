---
title: Layouts
description: Configure and switch between different window layouts.
---

## Supported Layouts

mangowm supports a variety of layouts that can be assigned per tag.

- `tile`
- `scroller`
- `scroller-deck`
- `monocle`
- `grid`
- `deck`
- `center_tile`
- `vertical_tile`
- `right_tile`
- `vertical_scroller`
- `vertical_grid`
- `vertical_deck`
- `dwindle`
- `fair`
- `vertical_fair`

---

## Scroller Layout

The Scroller layout positions windows in a scrollable strip, similar to PaperWM.

### Configuration

| Setting | Default | Description |
| :--- | :--- | :--- |
| `scroller_structs` | `20` | Width reserved on sides when window ratio is 1. |
| `scroller_default_proportion` | `0.9` | Default width proportion for new windows. |
| `scroller_focus_center` | `0` | Always center the focused window (1 = enable). |
| `scroller_prefer_center` | `0` | Center focused window only if it was outside the view. |
| `scroller_prefer_overspread` | `1` | Allow windows to overspread when there's extra space. |
| `edge_scroller_pointer_focus` | `1` | Focus windows even if partially off-screen. |
| `edge_scroller_focus_allow_speed` | `0.0` | Allow pointer focus to happen if the pointer moves at a speed greater than this value. |
| `scroller_proportion_preset` | `0.5,0.8,1.0` | Presets for cycling window widths. |
| `scroller_ignore_proportion_single` | `1` | Ignore proportion adjustments for single windows. |
| `scroller_default_proportion_single` | `1.0` | Default proportion for single windows in scroller. **Requires `scroller_ignore_proportion_single=0` to take effect.** |

> **Warning:** `scroller_prefer_overspread`, `scroller_focus_center`, and `scroller_prefer_center` interact with each other. Their priority order is:
>
> **scroller_prefer_overspread > scroller_focus_center > scroller_prefer_center**
>
> To ensure a lower-priority setting takes effect, you must set all higher-priority options to `0`.

```ini
# Example scroller configuration
scroller_structs=20
scroller_default_proportion=0.9
scroller_focus_center=0
scroller_prefer_center=0
scroller_prefer_overspread=1
edge_scroller_pointer_focus=1
edge_scroller_focus_allow_speed=0.0
scroller_default_proportion_single=1.0
scroller_proportion_preset=0.5,0.8,1.0
```

---

## Scroller-Deck Layout

`scroller-deck` combines the horizontal Scroller strip with Deck tabs. The first
N visible tiled windows stay outside the automatic deck; the remaining windows
share one column at the end of the strip. The entire strip scrolls with focus,
using the existing Scroller width, centering, gap and overspread settings.

For example, with `N=2`, `A B C D` becomes `A B [C D]`. Opening E while A is
focused produces `A E [B C D]`; opening E while C is focused produces
`A B [C E D]`. New windows are inserted immediately after the focused window,
including when it is in a manual split or a tab.

| Setting | Default | Description |
| :--- | :--- | :--- |
| `default_scroller_master_count` | `1` | Number of tiled windows excluded from the automatic deck (`0`–`1000`). |
| `deck_tab_mode` | `1` | Use the same tab strip and mouse behavior as Deck. Setting it to `0` keeps overlapping deck windows without tabs. |

The count is independent for each monitor and tag, and separate from
`default_master_count` / `incnmaster`. It can also be set with
`tag_rule=...,scroller_master_count:N`. Reloading the configuration reapplies the
default and tag rules, just like the existing master count.

- `N=0` puts every tiled window in one deck.
- `N` greater than or equal to the tiled window count leaves every window independent.
- Increasing N with `inc_scroller_master_count` or `set_scroller_master_count`
  promotes the active deck window to the next independent slot, preserving the
  relative order of all other windows and keeping keyboard focus. For
  `A B [C D E]` with E active, increasing N from 2 to 3 produces `A B E [C D]`.
  When focus is on an independent or floating window, the most recently focused
  eligible deck member is promoted; this also works with `deck_tab_mode=0`.
  If N increases by more than one, the remaining slots come from the deck's front.
  Decreasing N merges the last independent windows into the deck's front without
  reordering them; decreasing the example back to 2 produces `A B [E C D]`.
- Closing, minimizing, floating or moving an independent window out of the view
  lets the next eligible window take its place. Restoring a minimized window
  uses Mango's existing restore order, then recalculates membership.
- Closing the focused deck window selects its left neighbor in tab order. If
  there is no left neighbor, it selects the right neighbor without wrapping.
  For `A B [C D E]`, closing D selects C and closing C selects D, regardless of
  focus history. If no deck window remains, Mango uses its existing focus
  fallback. This also works with `deck_tab_mode=0`.
- A deck with one window has no tab strip.
- The deck shares one width, initialized from its first member. Changing tabs
  keeps that width; `set_proportion`, `switch_proportion_preset` and horizontal
  resizing affect the whole deck. Windows extracted from it retain their own
  Scroller widths.
- `focusdir,left/right` moves between columns, returning to the selected tab
  when entering the deck. `focusstack,next/prev` cycles through all visible
  windows in window order, including the independent windows.
- `focusdeck,next/prev` cycles only within the deck in window order, wrapping
  from the last member to the first and vice versa. For `A B [C D E]`, `next`
  from E selects C and `prev` from C selects E. It does nothing when focus is
  outside the deck, the deck has only one member, another layout is active, or
  overview is open. It also works with `deck_tab_mode=0`. Tabs can additionally
  be selected with the mouse.
- `exchange_client,left/right` swaps a master and a deck member on the same
  monitor in their window-order slots. The deck member becomes a master, and
  the old master replaces it as the active deck member. For `A B [C D E]` with D
  focused, exchanging left produces `A D [C B E]` with B active in the deck.
  Keyboard focus stays on the window that initiated the exchange (D in this
  example). This also works with `deck_tab_mode=0`.
- `scroller_stack` can join or split windows within the first N windows. N counts
  windows, including each member of a manual split. Automatic tabs temporarily
  replace any split that crosses into the deck; switching back to `scroller`
  restores its manual stack links.

```ini
default_scroller_master_count=1
deck_tab_mode=1
tag_rule=id:1,layout_name:scroller-deck,scroller_master_count:2
circle_layout=scroller-deck,scroller,tile

bind=SUPER,s,setlayout,scroller-deck
bind=SUPER,bracketright,inc_scroller_master_count,+1
bind=SUPER,bracketleft,inc_scroller_master_count,-1
bind=SUPER,backslash,set_scroller_master_count,2
bind=SUPER,Tab,focusdeck,next
bind=SUPER+SHIFT,Tab,focusdeck,prev
```

```sh
mmsg dispatch setlayout,scroller-deck
mmsg dispatch inc_scroller_master_count,+1
mmsg dispatch inc_scroller_master_count,-1
mmsg dispatch set_scroller_master_count,0
mmsg dispatch set_scroller_master_count,2
mmsg dispatch focusdeck,next
mmsg dispatch focusdeck,prev
```

`mmsg get monitor <name>` and `mmsg get tags <name>` expose each tag's
`scroller_master_count`. Client queries include `is_master`, `is_tab_focus` and
`is_tab_hidden` for inspecting membership and selection.

---

## Master-Stack Layouts

These settings apply to layouts like `tile` and `center_tile`.

| Setting | Default | Description |
| :--- | :--- | :--- |
| `new_is_master` | `1` | New windows become the master window. |
| `default_master_factor` | `0.55` | The split ratio between master and stack areas. |
| `default_master_count` | `1` | Number of allowed master windows. |
| `center_master_overspread` | `0` | (Center Tile) Master spreads across screen if no stack exists. |
| `center_when_single_stack` | `1` | (Center Tile) Center master when only one stack window exists. |

```ini
# Example master-stack configuration
new_is_master=1
smart_gaps=0
default_master_factor=0.55
default_master_count=1
tag_num=9
tag_gather=0
```

---

## Dwindle Layout

The Dwindle layout arranges windows as a binary tree of recursive splits. Each new window splits the focused window's container, producing a spiral-like tiling.

### Configuration

| Setting | Default | Description |
| :--- | :--- | :--- |
| `dwindle_split_ratio` | `0.5` | Ratio used for new splits (`0.05`–`0.95`). |
| `dwindle_smart_split` | `0` | Pick the split axis from the cursor's position inside the focused window. The new window appears on the cursor's side. |
| `dwindle_horizontal_split` | `1` | Side-by-side splits: where the new window goes. `0` = follow cursor, `1` = right, `2` = left. |
| `dwindle_vertical_split` | `1` | Top/bottom splits: where the new window goes. `0` = follow cursor, `1` = below, `2` = above. |
| `dwindle_preserve_split` | `0` | Keep the sibling's split orientation when a window is closed. |
| `dwindle_smart_resize` | `0` | When dragging to resize, move the split toward the cursor regardless of which side was grabbed. |
| `dwindle_drop_simple_split` | `1` | Drag-to-tile drop preview. `1` = 2-zone preview matching `dwindle_split_ratio`, `0` = 4-quadrant preview. |
| `dwindle_manual_split` | `0` | Manually split windows mode. |

```ini
# Example dwindle configuration
dwindle_split_ratio=0.5
dwindle_smart_split=0
dwindle_horizontal_split=0
dwindle_vertical_split=0
dwindle_preserve_split=0
dwindle_smart_resize=0
dwindle_drop_simple_split=1
```

---

## Monocle Layout

The Monocle layout shows a single window at a time, with the other windows on the tag stacked behind it.

### Configuration

| Setting | Default | Description |
| :--- | :--- | :--- |
| `monocle_tab_mode` | `1` | Auto merge stacked windows into a tab in monocle layout. |
| `monocle_right_button_close` | `0` | Right click on the tab bar closes that window. |
| `monocle_no_border` | `0` | Remove window borders from tiled windows (including maximized ones) while the monocle layout is active. |
| `monocle_no_gap` | `0` | Remove gaps around tiled windows (including maximized ones) while the monocle layout is active. |
| `monocle_no_radius` | `0` | Remove window corner radii (including maximized ones) while the monocle layout is active. |

```ini
# Example monocle configuration
monocle_tab_mode=1
monocle_right_button_close=0
monocle_no_border=0
monocle_no_gap=0
monocle_no_radius=0
```

---

## Deck Layout

The Deck layout keeps the master area visible and stacks the remaining windows as a deck of cards.

### Configuration

| Setting | Default | Description |
| :--- | :--- | :--- |
| `deck_tab_mode` | `1` | Auto merge stack area windows into a tab in deck layout. |

```ini
# Example deck configuration
deck_tab_mode=1
```

---

## Switching Layouts
| Setting | Default | Description |
| :--- | :--- | :--- |
| `circle_layout` | - | A comma-separated list of layouts `switch_layout` cycles through,the value sample:`tile,scroller`. |

You can switch layouts dynamically or set a default for specific tags using [Tag Rules](/docs/window-management/rules#tag-rules).

**Keybinding Examples:**

```ini
# Cycle through layouts
circle_layout=grid,scroller,tile
bind=SUPER,n,switch_layout

# Set specific layout
bind=SUPER,t,setlayout,tile
bind=SUPER,s,setlayout,scroller
```
