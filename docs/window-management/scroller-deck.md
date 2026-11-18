---
title: Scroller-Deck
description: Scroller columns with an automatic tabbed deck column.
---

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
  from E selects C and `prev` from C selects E. It always acts on the current
  tag's deck: with focus on an independent window, a floating window or
  nothing, it only switches the deck's active (displayed) member, stepping from
  the current one, and keyboard focus stays where it is: `next` from A with D
  active makes E the active tab while A keeps focus. It does nothing when the
  deck is empty, another layout is active, or overview is open. It also works
  with `deck_tab_mode=0`. Tabs can additionally be selected with the mouse.
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
