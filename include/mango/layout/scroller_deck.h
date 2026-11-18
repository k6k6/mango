#ifndef __LAYOUT_SCROLLER_DECK_H__
#define __LAYOUT_SCROLLER_DECK_H__ 1

/* scroller-deck keeps the first N visible scroller tiles as independent
 * columns (masters) and shows the remaining ones as a single tabbed column
 * (the deck). All layout-specific behaviour lives in scroller_deck.c; shared
 * code only calls the hooks below, which do nothing outside this layout.
 */

#include "mango/common/types.h"
#include <stdbool.h>
#include <stdint.h>
#include <wlr/util/box.h>

struct ScrollerStackNode;

struct ScrollerDeckTagState {
	int32_t master_count;
	/* Shared deck width; 0 until the deck is arranged for the first time. */
	float proportion;
};

typedef int32_t (*ScrollerDeckFunc)(const Arg *);

/* Layout */
void scroller_deck(Monitor *m);
bool scroller_deck_is_layout(Monitor *m);
bool scroller_deck_is_member(Client *c, Monitor *m);
Client *scroller_deck_active(Monitor *m);

/* Dispatch */
int32_t focus_deck(const Arg *arg);
int32_t inc_scroller_master_count(const Arg *arg);
int32_t set_scroller_master_count(const Arg *arg);
ScrollerDeckFunc scroller_deck_parse_func(const char *func_name, Arg *arg,
										  const char *arg_value);

/* Per-tag state */
void scroller_deck_tag_defaults(Monitor *m, uint32_t tag);
void scroller_deck_apply_tag_rule(Monitor *m, uint32_t tag,
								  int32_t master_count);
void scroller_deck_reset_tag(Monitor *m, uint32_t tag);
void scroller_deck_copy_tag(Pertag *dst, uint32_t dst_tag, const Pertag *src,
							uint32_t src_tag);
int32_t scroller_deck_nmasters(Monitor *m, uint32_t tag, int32_t nmasters);

/* Hooks into shared scroller/client code. A false/NULL/-1 result means the
 * caller continues with its regular behaviour. */
bool scroller_deck_arrange_column(struct ScrollerStackNode *head,
								  struct wlr_box geometry);
bool scroller_deck_stack_end(Client *c, bool tail, Client **out);
bool scroller_deck_resize(Client *gc, bool isdrag, int32_t offsetx,
						  int32_t offsety);
bool scroller_deck_set_proportion(Client *c, float proportion);
bool scroller_deck_switch_proportion_preset(Client *c);
bool scroller_deck_center_window(Client *c);
bool scroller_deck_blocks_stack(Client *c, Client *target);
bool scroller_deck_blocks_apply_stack(Client *c, Client *target,
									  int32_t *direction);
bool scroller_deck_drop_tile(Client *c, Client *closest);
bool scroller_deck_hidden_tab(Client *c);
int32_t scroller_deck_same_stack(Client *sc, Client *tc, Client *fc);
Client *scroller_deck_insert_anchor(Client *sel, Client *at_client);
Client *scroller_deck_focus_after_close(Client *c);
void scroller_deck_exchange(Client *c1, Client *c2);
Client *scroller_deck_tab_focus(Client *head);

#endif
