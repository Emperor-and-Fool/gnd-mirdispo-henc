/* The stream helper is found on D-Bus by the unit it was started as.
 *
 * Mirdispo reads a helper's state through its D-Bus name, so the name has to
 * follow from the unit name alone, and the daemon has to hand that unit name
 * to the helper whether systemd starts it or the daemon does. */
#include <glib.h>

#include "nd-systemd-helpers.h"
#include "stream/nd-stream.h"

#define CONNECTION "0f1e2d3c-4b5a-6978-8796-a5b4c3d2e1f0"
#define UNIT "gnome-network-displays-stream-11111111-2222-3333-4444-555555555555-" CONNECTION ".service"

int
main (void)
{
  g_autofree gchar *id = nd_stream_application_id (UNIT);
  g_autofree gchar *random_id = nd_stream_application_id (NULL);
  g_autofree gchar *bad_id = nd_stream_application_id ("something-else.service");
  g_autoptr(GVariant) properties = build_properties (UNIT, "gnome-network-displays://sink", "TV");
  GVariantIter iter;
  const gchar *key;
  GVariant *value;
  gboolean found = FALSE;

  g_assert_cmpstr (id, ==, ND_BUS_PREFIX ".Stream_0f1e2d3c_4b5a_6978_8796_a5b4c3d2e1f0");
  g_assert_true (g_application_id_is_valid (id));

  /* Without a unit the name stays random but valid, as upstream had it. */
  g_assert_true (g_str_has_prefix (random_id, ND_BUS_PREFIX ".Stream_"));
  g_assert_true (g_application_id_is_valid (random_id));
  g_assert_true (g_application_id_is_valid (bad_id));

  /* systemd passes the unit name on in the helper's environment. */
  g_variant_iter_init (&iter, properties);
  while (g_variant_iter_next (&iter, "(&sv)", &key, &value))
    {
      if (g_str_equal (key, "Environment"))
        {
          g_autofree const gchar **env = g_variant_get_strv (value, NULL);
          found = g_strv_contains (env, "ND_STREAM_UNIT=" UNIT);
        }
      g_variant_unref (value);
    }
  g_assert_true (found);

  return 0;
}
