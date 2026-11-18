#include "mango/layout/scroller_deck.h"
#include "mango/common/server.h"
#include "mango/common/util.h"
#include "mango/config/parse.h"
#include "mango/dispatch/bind.h"
#include "mango/input/pointer.h"
#include "mango/layout/arrange.h"
#include "mango/layout/layout.h"
#include "mango/layout/scroll.h"
#include "mango/manage/client.h"
#include "mango/manage/monitor.h"
#include "mango/manage/tab.h"
#include <stdlib.h>
#include <string.h>
#include <wlr/types/wlr_compositor.h>
#include <wlr/types/wlr_cursor.h>

/* Deck member whose column the shared scroller code is arranging right now. */
static Client *arranging_active;
/* Set while a master resize runs through the shared scroller resize. */
static bool resizing_master;

static bool deck_on_tag(Monitor *m, uint32_t tag) {
	return m && m->pertag->ltidxs[tag]->id == SCROLLER_DECK;
}

static bool deck_on_client_tag(Client *c) {
	return c && deck_on_tag(c->mon, get_client_tag_idx(c));
}

bool scroller_deck_is_layout(Monitor *m) {
	return m && deck_on_tag(m, get_mon_curtag(m));
}

bool scroller_deck_is_member(Client *c, Monitor *m) {
	return c && m && VISIBLEON(c, m) && ISSCROLLTILED(c) && !c->ismaster;
}

static Client *deck_first(Monitor *m) {
	Client *c;
	wl_list_for_each(c, &server.clients, link) {
		if (scroller_deck_is_member(c, m))
			return c;
	}
	return NULL;
}

static Client *deck_last(Monitor *m) {
	Client *c;
	wl_list_for_each_reverse(c, &server.clients, link) {
		if (scroller_deck_is_member(c, m))
			return c;
	}
	return NULL;
}

/* The deck's active member: the focused deck client, otherwise the most
 * recently focused one. It is the deck column's anchor, so it is the visible
 * tab even with focus on a master or floating window and tabs off. */
Client *scroller_deck_active(Monitor *m) {
	Client *c;
	if (!m)
		return NULL;
	if (scroller_deck_is_member(m->sel, m))
		return m->sel;
	wl_list_for_each(c, &server.focus_stack, flink) {
		if (scroller_deck_is_member(c, m))
			return c;
	}
	return NULL;
}

/* Shared deck width; before the first arrange it is the first member's. */
static float deck_proportion(Monitor *m, uint32_t tag) {
	if (m->pertag->scroller_deck[tag].proportion > 0.0f)
		return m->pertag->scroller_deck[tag].proportion;
	Client *first = deck_first(m);
	if (!first)
		return 0.0f;
	struct ScrollerStackNode *node =
		find_scroller_node(m->pertag->scroller_state[tag], first);
	return node ? node->scroller_proportion : first->scroller_proportion;
}

/* ---- Layout ---- */

struct DeckView {
	struct TagScrollerState st;
	struct ScrollerStackNode *nodes;
	struct ScrollerStackNode **originals;
};

/* Real nodes sorted by client, so the view is built in O(n log n) instead of
 * a linear find_scroller_node() per window. view is the matching view node. */
struct DeckIndex {
	Client *client;
	struct ScrollerStackNode *real;
	struct ScrollerStackNode *view;
};

static int deck_index_cmp(const void *a, const void *b) {
	uintptr_t ca = (uintptr_t)((const struct DeckIndex *)a)->client;
	uintptr_t cb = (uintptr_t)((const struct DeckIndex *)b)->client;
	return ca < cb ? -1 : ca > cb;
}

static struct DeckIndex *deck_index_find(struct DeckIndex *index, int32_t n,
										 Client *c) {
	struct DeckIndex key = {.client = c};
	return bsearch(&key, index, n, sizeof(*index), deck_index_cmp);
}

/* Build a layout-only scroller state: masters keep their manual splits among
 * themselves, and the deck is one column headed by its active member. The
 * real state is never changed, so splits crossing the master/deck boundary
 * survive master-count changes and layout switches. */
static bool deck_view_build(Monitor *m, struct TagScrollerState *real,
							Client *active, struct DeckView *v) {
	int32_t size = real->count ? real->count : 1;
	memset(v, 0, sizeof(*v));
	v->nodes = calloc(size, sizeof(*v->nodes));
	v->originals = calloc(size, sizeof(*v->originals));
	struct DeckIndex *index = calloc(size, sizeof(*index));
	if (!v->nodes || !v->originals || !index) {
		free(v->nodes);
		free(v->originals);
		free(index);
		return false;
	}

	int32_t n_index = 0;
	for (struct ScrollerStackNode *n = real->all_first; n && n_index < size;
		 n = n->all_next)
		index[n_index++] = (struct DeckIndex){.client = n->client, .real = n};
	qsort(index, n_index, sizeof(*index), deck_index_cmp);

	uint32_t tag = get_mon_curtag(m);
	float proportion = deck_proportion(m, tag);
	struct DeckIndex *first = deck_index_find(index, n_index, deck_first(m));
	struct ScrollerStackNode *tail = NULL;
	Client *c;
	wl_list_for_each(c, &server.clients, link) {
		if (v->st.count >= size)
			break;
		if (!VISIBLEON(c, m) || !ISSCROLLTILED(c) ||
			(!c->ismaster && c != active))
			continue;
		struct DeckIndex *entry = deck_index_find(index, n_index, c);
		if (!entry)
			continue;
		struct ScrollerStackNode *node = &v->nodes[v->st.count];
		v->originals[v->st.count++] = entry->real;
		entry->view = node;
		*node = *entry->real;
		node->prev_in_stack = node->next_in_stack = node->all_next = NULL;
		if (c == active) {
			node->scroller_proportion = proportion;
			if (first)
				node->scroller_proportion_single =
					first->real->scroller_proportion_single;
		}
		if (tail)
			tail->all_next = node;
		else
			v->st.all_first = node;
		tail = node;
	}

	for (int32_t i = 0; i < v->st.count; i++) {
		struct ScrollerStackNode *next = v->originals[i]->next_in_stack;
		if (!v->nodes[i].client->ismaster || !next || !next->client->ismaster)
			continue;
		struct DeckIndex *entry = deck_index_find(index, n_index, next->client);
		if (entry && entry->view) {
			v->nodes[i].next_in_stack = entry->view;
			entry->view->prev_in_stack = &v->nodes[i];
		}
	}
	free(index);
	return true;
}

/* Run the regular scroller with the deck view in place of the tag state. */
void scroller_deck(Monitor *m) {
	uint32_t tag = get_mon_curtag(m);
	struct TagScrollerState *real = ensure_scroller_state(m, tag);
	if (!real)
		return;
	Client *active = scroller_deck_active(m);
	if (active && m->pertag->scroller_deck[tag].proportion <= 0.0f)
		m->pertag->scroller_deck[tag].proportion = deck_proportion(m, tag);

	struct DeckView v;
	if (!deck_view_build(m, real, active, &v))
		return;

	/* Hidden tabs are not in the view: a deck m->prevsel stands for the
	 * active member, whose width the shared code reads from the client.
	 * The same holds when the scroller would root on the tiled client
	 * nearest the monitor center and that is a hidden tab. */
	Client *prevsel = m->prevsel;
	if (active && (scroller_deck_is_member(prevsel, m) ||
				   (m->sel && !find_scroller_node(&v.st, m->sel) &&
					scroller_deck_is_member(center_tiled_select(m), m)))) {
		m->prevsel = active;
		active->scroller_proportion = deck_proportion(m, tag);
	}

	m->pertag->scroller_state[tag] = &v.st;
	arranging_active = active;
	scroller(m);
	arranging_active = NULL;
	m->pertag->scroller_state[tag] = real;
	m->prevsel = prevsel;

	for (int32_t i = 0; i < v.st.count; i++) {
		if (!v.nodes[i].client->ismaster)
			continue;
		v.originals[i]->scroller_stack_proportion =
			v.nodes[i].scroller_stack_proportion;
		v.originals[i]->scroller_stack_weight =
			v.nodes[i].scroller_stack_weight;
	}
	/* The shared code synced the view into the client fields; restore the
	 * real state, as a regular scroller arrange leaves it. */
	sync_scroller_state_to_clients(m, tag);
	free(v.nodes);
	free(v.originals);
}

/* Every deck member shares the active member's column geometry. */
bool scroller_deck_arrange_column(struct ScrollerStackNode *head,
								  struct wlr_box geometry) {
	if (!arranging_active || !head || head->client != arranging_active)
		return false;
	Monitor *m = arranging_active->mon;
	Client *c;
	wl_list_for_each(c, &server.clients, link) {
		if (!scroller_deck_is_member(c, m))
			continue;
		client_tile_resize(c, geometry, 0);
		client_update_visibility(c);
	}
	return true;
}

/* ---- Stacks ---- */

/* Deck members form one stack spanning the whole deck; master stacks end at
 * the master/deck boundary. */
bool scroller_deck_stack_end(Client *c, bool tail, Client **out) {
	if (!c || !c->mon || !deck_on_client_tag(c) || !ISSCROLLTILED(c) ||
		!VISIBLEON(c, c->mon))
		return false;

	if (!c->ismaster) {
		Client *end = tail ? deck_last(c->mon) : deck_first(c->mon);
		*out = end ? end : c;
		return true;
	}

	struct ScrollerStackNode *n = find_scroller_node(
		c->mon->pertag->scroller_state[get_client_tag_idx(c)], c);
	if (!n)
		return false;
	for (;;) {
		struct ScrollerStackNode *next =
			tail ? n->next_in_stack : n->prev_in_stack;
		if (!next || !next->client->ismaster)
			break;
		n = next;
	}
	*out = n->client;
	return true;
}

bool scroller_deck_blocks_stack(Client *c, Client *target) {
	if (!deck_on_client_tag(c))
		return false;
	return target == c || !c->ismaster || !target->ismaster;
}

/* The shared code treats every layout except Scroller as vertical, so map
 * the deck's horizontal directions onto the vertical ones. */
bool scroller_deck_blocks_apply_stack(Client *c, Client *target,
									  int32_t *direction) {
	if (!deck_on_client_tag(c))
		return false;
	if (!c->ismaster || *direction == UP || *direction == DOWN)
		return true;
	if (*direction == LEFT)
		*direction = UP;
	else if (*direction == RIGHT)
		*direction = DOWN;

	/* Only masters can be stacked; leaving a stack needs no target. */
	if (target && !target->ismaster) {
		struct ScrollerStackNode *node = find_scroller_node(
			c->mon->pertag->scroller_state[get_client_tag_idx(c)], c);
		if (!node || (!node->prev_in_stack && !node->next_in_stack))
			return true;
	}
	return false;
}

/* Dropping into or out of the deck only reorders windows. */
bool scroller_deck_drop_tile(Client *c, Client *closest) {
	if (!closest || !deck_on_tag(closest->mon, get_mon_curtag(closest->mon)) ||
		(c->ismaster && closest->ismaster))
		return false;
	client_set_floating(c, 0, false);
	if (closest->drop_direction == LEFT || closest->drop_direction == UP)
		wl_list_safe_reinsert_prev(&closest->link, &c->link);
	else
		wl_list_safe_reinsert_next(&closest->link, &c->link);
	arrange(closest->mon, false, false);
	return true;
}

/* ---- Sizes ---- */

static void deck_set_proportion(Monitor *m, uint32_t tag, float proportion) {
	m->pertag->scroller_deck[tag].proportion = proportion;
}

bool scroller_deck_set_proportion(Client *c, float proportion) {
	if (!c || !deck_on_client_tag(c) || !scroller_deck_is_member(c, c->mon))
		return false;
	Monitor *m = c->mon;
	deck_set_proportion(m, get_client_tag_idx(c), proportion);
	uint32_t max_client_width =
		m->w.width - 2 * config.scroller_structs - config.gappih;
	c->geom.width = max_client_width * proportion;
	arrange(m, false, false);
	return true;
}

bool scroller_deck_switch_proportion_preset(Client *c) {
	if (!c || !deck_on_client_tag(c) || !scroller_deck_is_member(c, c->mon))
		return false;
	float current = deck_proportion(c->mon, get_client_tag_idx(c));
	float target = 0.0f;
	for (int32_t i = 0; i < config.scroller_proportion_preset_count; i++) {
		if (config.scroller_proportion_preset[i] == current) {
			if (i == config.scroller_proportion_preset_count - 1)
				target = config.scroller_proportion_preset[0];
			else
				target = config.scroller_proportion_preset[i + 1];
			break;
		}
	}
	if (target == 0.0f)
		target = config.scroller_proportion_preset[0];
	return scroller_deck_set_proportion(c, target);
}

static bool resize_deck_member(Client *gc, bool isdrag, int32_t offsetx) {
	Monitor *m = gc->mon;
	uint32_t tag = get_client_tag_idx(gc);
	if (!server.start_drag_window && isdrag) {
		server.drag_begin_cursor_x = server.cursor->x;
		server.drag_begin_cursor_y = server.cursor->y;
		server.start_drag_window = true;
		gc->old_scroller_pproportion = deck_proportion(m, tag);
		gc->drag_begin_geom = gc->geom;
		gc->cursor_in_left_half =
			server.cursor->x < gc->geom.x + gc->geom.width / 2;
		return true;
	}
	if (isdrag) {
		offsetx = server.cursor->x - server.drag_begin_cursor_x;
		if (gc->cursor_in_left_half)
			offsetx = -offsetx;
	} else {
		gc->old_scroller_pproportion = deck_proportion(m, tag);
		gc->drag_begin_geom = gc->geom;
	}
	if (gc->drag_begin_geom.width <= 0)
		return true;
	float proportion = gc->old_scroller_pproportion *
					   (1.0f + (float)offsetx / gc->drag_begin_geom.width);
	deck_set_proportion(m, tag, CLAMP_FLOAT(proportion, 0.1f, 1.0f));
	arrange(m, false, false);
	return true;
}

struct DeckLink {
	Client *prev, *next;
};

/* Masters reuse the shared scroller resize. Split links that cross into the
 * deck are hidden meanwhile, so only the master part of a split is resized,
 * and restored afterwards. */
static void resize_master(Client *gc, bool isdrag, int32_t offsetx,
						  int32_t offsety) {
	struct TagScrollerState *st =
		gc->mon->pertag->scroller_state[get_client_tag_idx(gc)];
	struct DeckLink *links = NULL;
	int32_t n_links = 0;
	if (st && st->count > 0)
		links = calloc(st->count, sizeof(*links));
	if (links) {
		for (struct ScrollerStackNode *n = st->all_first; n; n = n->all_next) {
			struct ScrollerStackNode *next = n->next_in_stack;
			if (!next || n->client->ismaster == next->client->ismaster ||
				n_links >= st->count)
				continue;
			links[n_links++] = (struct DeckLink){n->client, next->client};
			n->next_in_stack = NULL;
			next->prev_in_stack = NULL;
		}
	}

	resizing_master = true;
	resize_tile_scroller(gc, isdrag, offsetx, offsety, false);
	resizing_master = false;

	st = gc->mon->pertag->scroller_state[get_client_tag_idx(gc)];
	for (int32_t i = 0; i < n_links; i++) {
		struct ScrollerStackNode *prev = find_scroller_node(st, links[i].prev);
		struct ScrollerStackNode *next = find_scroller_node(st, links[i].next);
		if (prev && next && !prev->next_in_stack && !next->prev_in_stack) {
			prev->next_in_stack = next;
			next->prev_in_stack = prev;
		}
	}
	free(links);
}

bool scroller_deck_resize(Client *gc, bool isdrag, int32_t offsetx,
						  int32_t offsety) {
	if (resizing_master || !gc || !gc->mon || !deck_on_client_tag(gc))
		return false;
	if (!gc->ismaster)
		return resize_deck_member(gc, isdrag, offsetx);
	resize_master(gc, isdrag, offsetx, offsety);
	return true;
}

/* Center the window's column horizontally; the shared code would treat the
 * deck as a vertical scroller and anchor the wrong deck member. */
bool scroller_deck_center_window(Client *c) {
	if (!c || !c->mon || !deck_on_client_tag(c) || !ISSCROLLTILED(c))
		return false;
	Monitor *m = c->mon;
	Client *column =
		c->ismaster ? scroll_get_stack_head_client(c) : scroller_deck_active(m);
	if (!column)
		column = c;
	column->geom.x = m->w.x + (m->w.width - column->geom.width) / 2;
	arrange(m, false, false);
	return true;
}

/* ---- Focus ---- */

bool scroller_deck_hidden_tab(Client *c) {
	return c && c->mon && !c->mon->isoverview && c->is_tab_hidden &&
		   scroller_deck_is_layout(c->mon);
}

int32_t scroller_deck_same_stack(Client *sc, Client *tc, Client *fc) {
	if (!deck_on_client_tag(sc))
		return -1;
	if (sc->mon != tc->mon)
		return 0;
	if (!sc->ismaster && !tc->ismaster)
		return !tc->is_tab_hidden;
	if (sc->ismaster != tc->ismaster)
		return 0;

	Client *source_head = scroll_get_stack_head_client(sc);
	if (fc && scroll_get_stack_head_client(fc) == source_head)
		return 0;
	return source_head == scroll_get_stack_head_client(tc);
}

/* New windows open right after the focused window, not after its stack. */
Client *scroller_deck_insert_anchor(Client *sel, Client *at_client) {
	return scroller_deck_is_layout(server.selected_monitor) ? sel : at_client;
}

/* Closing a deck member focuses its left deck neighbor, or the right one at
 * the left edge without wrapping. Called before unmap changes membership;
 * tab links may be absent when deck_tab_mode=0. */
Client *scroller_deck_focus_after_close(Client *c) {
	Monitor *m = c->mon;
	if (!m || m != server.selected_monitor || c != m->sel || m->isoverview ||
		!scroller_deck_is_layout(m) || !scroller_deck_is_member(c, m) ||
		c->swallowing || client_is_group_member(c))
		return NULL;

	Client *it, *left = NULL;
	bool after = false;
	wl_list_for_each(it, &server.clients, link) {
		if (it == c) {
			if (left)
				return left;
			after = true;
			continue;
		}
		if (!scroller_deck_is_member(it, m) || it->no_focus ||
			!client_surface(it)->mapped)
			continue;
		if (after)
			return it;
		left = it;
	}
	return NULL;
}

/* A master/deck exchange hands the deck member's tab slot to the old master
 * before arrange can detach it and activate another tab. The focus history
 * keeps the column anchor in sync, also when deck_tab_mode=0. */
void scroller_deck_exchange(Client *c1, Client *c2) {
	Monitor *m = c1->mon;
	if (!m || m != c2->mon || m->isoverview || !deck_on_client_tag(c1) ||
		!VISIBLEON(c1, m) || !ISSCROLLTILED(c1) || !VISIBLEON(c2, m) ||
		!ISSCROLLTILED(c2) || c1->ismaster == c2->ismaster)
		return;
	Client *master = c1->ismaster ? c1 : c2;
	Client *deck = c1->ismaster ? c2 : c1;
	tab_replace_client(deck, master);
	tab_sync_focus(master);
	wl_list_safe_reinsert_next(&c1->flink, &c2->flink);
}

/* Switching tags detaches the old tab chain and clears its active marker. If
 * focus returns to a master, restore the most recently focused deck member
 * instead of selecting the first tab when rebuilding the chain. */
Client *scroller_deck_tab_focus(Client *head) {
	if (!head || !scroller_deck_is_layout(head->mon))
		return NULL;
	Client *c;
	wl_list_for_each(c, &server.focus_stack, flink) {
		if (c->mon != head->mon)
			continue;
		Client *h = c;
		while (h->tab_prev)
			h = h->tab_prev;
		if (h == head)
			return c;
	}
	return NULL;
}

int32_t focus_deck(const Arg *arg) {
	Monitor *m = server.selected_monitor;
	if (!arg || !m || m->isoverview || !scroller_deck_is_layout(m))
		return 0;

	/* Always act on the current tag's deck. With keyboard focus outside it
	 * (master, floating, nothing), step from the deck's active member and
	 * only switch which member is active; focus stays where it is.
	 */
	bool focus_in_deck = scroller_deck_is_member(m->sel, m);
	Client *active = scroller_deck_active(m);
	Client *sel = arg->tc ? arg->tc : client_focus_top(m);
	if (!scroller_deck_is_member(sel, m))
		sel = active;
	if (!sel)
		return 0;

	/* Use layout membership, not tab links: deck_tab_mode=0 has no tab chain.
	 * Start at sel so both directions wrap without ever leaving the deck; a
	 * singleton deck yields sel itself.
	 */
	Client *target = sel;
	bool reverse = arg->i != NEXT;
	for (struct wl_list *link = reverse ? sel->link.prev : sel->link.next;
		 link != &sel->link; link = reverse ? link->prev : link->next) {
		if (link == &server.clients)
			continue;
		Client *tc = wl_container_of(link, tc, link);
		if (scroller_deck_is_member(tc, m)) {
			target = tc;
			break;
		}
	}

	if (focus_in_deck) {
		if (target == m->sel)
			return 0;
		client_focus(target, 1);
		if (config.warpcursor)
			pointer_warp_to_client(target);
		return 0;
	}

	/* The layout's column anchor is the most recently focused deck member:
	 * move target just ahead of the current one in focus history (behind the
	 * focused window) and activate its tab, then re-arrange.
	 */
	if (target == active)
		return 0;
	wl_list_safe_reinsert_prev(&active->flink, &target->flink);
	tab_sync_focus(target);
	arrange(m, false, false);
	return 0;
}

/* ---- Master count ---- */

static void promote_active(Monitor *m) {
	Client *active = scroller_deck_active(m);
	Client *first = deck_first(m);
	/* The first deck slot becomes the next master. Keep every other client's
	 * relative order and leave saved manual scroller stack links intact. */
	if (active && first)
		wl_list_safe_reinsert_prev(&first->link, &active->link);
}

static int32_t update_master_count(const Arg *arg, bool relative) {
	Monitor *m = server.selected_monitor;
	if (!arg || !m)
		return 0;
	uint32_t tag = get_mon_curtag(m);
	int32_t old_count = m->pertag->scroller_deck[tag].master_count;
	int64_t count = arg->i;
	if (relative)
		count += old_count;
	count = MANGO_MAX(0, MANGO_MIN(count, 1000));
	if (count > old_count && !m->isoverview && deck_on_tag(m, tag))
		promote_active(m);
	m->pertag->scroller_deck[tag].master_count = count;
	arrange(m, false, false);
	return 0;
}

int32_t inc_scroller_master_count(const Arg *arg) {
	return update_master_count(arg, true);
}

int32_t set_scroller_master_count(const Arg *arg) {
	return update_master_count(arg, false);
}

ScrollerDeckFunc scroller_deck_parse_func(const char *func_name, Arg *arg,
										  const char *arg_value) {
	if (strcmp(func_name, "focusdeck") == 0) {
		arg->i = parse_circle_direction(arg_value);
		return focus_deck;
	}
	if (strcmp(func_name, "inc_scroller_master_count") == 0) {
		arg->i = atoi(arg_value);
		return inc_scroller_master_count;
	}
	if (strcmp(func_name, "set_scroller_master_count") == 0) {
		arg->i = atoi(arg_value);
		return set_scroller_master_count;
	}
	return NULL;
}

/* ---- Per-tag state ---- */

void scroller_deck_tag_defaults(Monitor *m, uint32_t tag) {
	m->pertag->scroller_deck[tag].master_count =
		config.default_scroller_master_count;
}

void scroller_deck_apply_tag_rule(Monitor *m, uint32_t tag,
								  int32_t master_count) {
	if (master_count >= 0)
		m->pertag->scroller_deck[tag].master_count = master_count;
}

void scroller_deck_reset_tag(Monitor *m, uint32_t tag) {
	m->pertag->scroller_deck[tag].proportion = 0.0f;
}

void scroller_deck_copy_tag(Pertag *dst, uint32_t dst_tag, const Pertag *src,
							uint32_t src_tag) {
	dst->scroller_deck[dst_tag] = src->scroller_deck[src_tag];
}

int32_t scroller_deck_nmasters(Monitor *m, uint32_t tag, int32_t nmasters) {
	return deck_on_tag(m, tag) ? m->pertag->scroller_deck[tag].master_count
							   : nmasters;
}
