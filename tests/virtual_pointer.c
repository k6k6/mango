/* Headless integration helper: move/click through the virtual pointer protocol.
 * Build with a client header/code generated from
 * wlr-virtual-pointer-unstable-v1.xml and link with wayland-client. */
#include "virtual-pointer-protocol.h"
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <time.h>
#include <wayland-client.h>

static struct zwlr_virtual_pointer_manager_v1 *manager;

static void registry_global(void *data, struct wl_registry *registry,
							uint32_t name, const char *interface,
							uint32_t version) {
	if (strcmp(interface, zwlr_virtual_pointer_manager_v1_interface.name) == 0)
		manager = wl_registry_bind(
			registry, name, &zwlr_virtual_pointer_manager_v1_interface, 1);
}

static void registry_remove(void *data, struct wl_registry *registry,
							uint32_t name) {}

int main(int argc, char **argv) {
	if (argc != 5 && argc != 6) {
		fprintf(stderr, "usage: %s x y width height [click]\n", argv[0]);
		return 2;
	}
	struct wl_display *display = wl_display_connect(NULL);
	if (!display)
		return 1;
	struct wl_registry *registry = wl_display_get_registry(display);
	static const struct wl_registry_listener listener = {
		.global = registry_global, .global_remove = registry_remove};
	wl_registry_add_listener(registry, &listener, NULL);
	if (wl_display_roundtrip(display) < 0 || !manager)
		return 1;

	struct zwlr_virtual_pointer_v1 *pointer =
		zwlr_virtual_pointer_manager_v1_create_virtual_pointer(manager, NULL);
	struct timespec now;
	clock_gettime(CLOCK_MONOTONIC, &now);
	uint32_t milliseconds = now.tv_sec * 1000 + now.tv_nsec / 1000000;
	zwlr_virtual_pointer_v1_motion_absolute(pointer, milliseconds,
											atoi(argv[1]), atoi(argv[2]),
											atoi(argv[3]), atoi(argv[4]));
	zwlr_virtual_pointer_v1_frame(pointer);
	if (wl_display_roundtrip(display) < 0)
		return 1;
	if (argc == 6) {
		zwlr_virtual_pointer_v1_button(pointer, milliseconds, 0x110,
									   WL_POINTER_BUTTON_STATE_PRESSED);
		zwlr_virtual_pointer_v1_frame(pointer);
		zwlr_virtual_pointer_v1_button(pointer, milliseconds + 1, 0x110,
									   WL_POINTER_BUTTON_STATE_RELEASED);
		zwlr_virtual_pointer_v1_frame(pointer);
		if (wl_display_roundtrip(display) < 0)
			return 1;
	}
	zwlr_virtual_pointer_v1_destroy(pointer);
	zwlr_virtual_pointer_manager_v1_destroy(manager);
	wl_registry_destroy(registry);
	wl_display_disconnect(display);
	return 0;
}
