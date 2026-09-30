#include <glib.h>

#include "nd-systemd-helpers.h"

int
main (void)
{
  g_autofree gchar *first = build_stream_unit_name ("sink-id");
  g_autofree gchar *second = build_stream_unit_name ("sink-id");

  g_assert_true (g_str_has_prefix (first,
                                   "gnome-network-displays-stream-sink-id-"));
  g_assert_true (g_str_has_suffix (first, ".service"));
  g_assert_cmpstr (first, !=, second);

  return 0;
}
