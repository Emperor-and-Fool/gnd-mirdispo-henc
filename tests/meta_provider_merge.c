/* Regression test for the meta provider use-after-free.
 *
 * A receiver that is discovered over two protocols first produces two
 * separate meta sinks. When a later sink matches both of them, the meta
 * provider merges them. Before the fix, it dropped the provider's only
 * reference to the merged meta sink by removing it from an array with a
 * g_object_unref free function, and then kept using that pointer: it emitted
 * "sink-removed" with it and walked its sink list. The daemon segfaulted
 * inside the signal emission, which took discovery down with it.
 */

#include <glib.h>

#include "nd-meta-provider.h"
#include "nd-provider.h"
#include "nd-sink.h"

/* A minimal NdSink whose match keys the test controls. */

#define TEST_TYPE_SINK (test_sink_get_type ())
G_DECLARE_FINAL_TYPE (TestSink, test_sink, TEST, SINK, GObject)

struct _TestSink
{
  GObject  parent_instance;
  GStrv    matches;
  gchar   *name;
};

enum {
  PROP_SINK_DISPLAY_NAME = 1,
  PROP_SINK_MATCHES,
  PROP_SINK_PRIORITY,
  PROP_SINK_STATE,
  PROP_SINK_PROTOCOL,
  PROP_SINK_MISSING_VIDEO_CODEC,
  PROP_SINK_MISSING_AUDIO_CODEC,
  PROP_SINK_MISSING_FIREWALL_ZONE,
  PROP_SINK_UUID,
};

static void test_sink_sink_iface_init (NdSinkIface *iface);

G_DEFINE_TYPE_WITH_CODE (TestSink, test_sink, G_TYPE_OBJECT,
                         G_IMPLEMENT_INTERFACE (ND_TYPE_SINK, test_sink_sink_iface_init))

static NdSink *
test_sink_start_stream (NdSink *sink)
{
  return sink;
}

static void
test_sink_stop_stream (NdSink *sink)
{
}

static gchar *
test_sink_to_uri (NdSink *sink)
{
  return g_strdup ("test://sink");
}

static void
test_sink_sink_iface_init (NdSinkIface *iface)
{
  iface->start_stream = test_sink_start_stream;
  iface->stop_stream = test_sink_stop_stream;
  iface->to_uri = test_sink_to_uri;
}

static void
test_sink_get_property (GObject *object, guint prop_id, GValue *value, GParamSpec *pspec)
{
  TestSink *self = TEST_SINK (object);

  switch (prop_id)
    {
    case PROP_SINK_DISPLAY_NAME:
      g_value_set_string (value, self->name);
      break;

    case PROP_SINK_MATCHES:
      {
        GPtrArray *res = g_ptr_array_new_with_free_func (g_free);

        for (gchar **m = self->matches; m && *m; m++)
          g_ptr_array_add (res, g_strdup (*m));

        g_value_take_boxed (value, res);
      }
      break;

    case PROP_SINK_PRIORITY:
      g_value_set_int (value, 100);
      break;

    case PROP_SINK_STATE:
      g_value_set_enum (value, ND_SINK_STATE_DISCONNECTED);
      break;

    case PROP_SINK_PROTOCOL:
      g_value_set_enum (value, ND_SINK_PROTOCOL_WFD_P2P);
      break;

    case PROP_SINK_MISSING_VIDEO_CODEC:
    case PROP_SINK_MISSING_AUDIO_CODEC:
      g_value_set_boxed (value, NULL);
      break;

    case PROP_SINK_MISSING_FIREWALL_ZONE:
      g_value_set_boolean (value, FALSE);
      break;

    case PROP_SINK_UUID:
      g_value_set_string (value, self->name);
      break;

    default:
      G_OBJECT_WARN_INVALID_PROPERTY_ID (object, prop_id, pspec);
      break;
    }
}

static void
test_sink_finalize (GObject *object)
{
  TestSink *self = TEST_SINK (object);

  g_clear_pointer (&self->matches, g_strfreev);
  g_clear_pointer (&self->name, g_free);

  G_OBJECT_CLASS (test_sink_parent_class)->finalize (object);
}

static void
test_sink_class_init (TestSinkClass *klass)
{
  GObjectClass *object_class = G_OBJECT_CLASS (klass);

  object_class->get_property = test_sink_get_property;
  object_class->finalize = test_sink_finalize;

  g_object_class_override_property (object_class, PROP_SINK_DISPLAY_NAME, "display-name");
  g_object_class_override_property (object_class, PROP_SINK_MATCHES, "matches");
  g_object_class_override_property (object_class, PROP_SINK_PRIORITY, "priority");
  g_object_class_override_property (object_class, PROP_SINK_STATE, "state");
  g_object_class_override_property (object_class, PROP_SINK_PROTOCOL, "protocol");
  g_object_class_override_property (object_class, PROP_SINK_MISSING_VIDEO_CODEC, "missing-video-codec");
  g_object_class_override_property (object_class, PROP_SINK_MISSING_AUDIO_CODEC, "missing-audio-codec");
  g_object_class_override_property (object_class, PROP_SINK_MISSING_FIREWALL_ZONE, "missing-firewall-zone");
  g_object_class_override_property (object_class, PROP_SINK_UUID, "uuid");
}

static void
test_sink_init (TestSink *self)
{
}

static NdSink *
test_sink_new (const gchar *name, const gchar * const *matches)
{
  TestSink *self = g_object_new (TEST_TYPE_SINK, NULL);

  self->name = g_strdup (name);
  self->matches = g_strdupv ((GStrv) matches);

  return ND_SINK (self);
}

/* A minimal NdProvider the test feeds sinks through. */

#define TEST_TYPE_PROVIDER (test_provider_get_type ())
G_DECLARE_FINAL_TYPE (TestProvider, test_provider, TEST, PROVIDER, GObject)

struct _TestProvider
{
  GObject    parent_instance;
  gboolean   discover;
  GPtrArray *sinks;
};

enum {
  PROP_PROVIDER_DISCOVER = 1,
};

static void test_provider_provider_iface_init (NdProviderIface *iface);

G_DEFINE_TYPE_WITH_CODE (TestProvider, test_provider, G_TYPE_OBJECT,
                         G_IMPLEMENT_INTERFACE (ND_TYPE_PROVIDER,
                                                test_provider_provider_iface_init))

static GList *
test_provider_get_sinks (NdProvider *provider)
{
  TestProvider *self = TEST_PROVIDER (provider);
  GList *res = NULL;

  for (guint i = 0; i < self->sinks->len; i++)
    res = g_list_prepend (res, g_ptr_array_index (self->sinks, i));

  return res;
}

static void
test_provider_provider_iface_init (NdProviderIface *iface)
{
  iface->get_sinks = test_provider_get_sinks;
}

static void
test_provider_get_property (GObject *object, guint prop_id, GValue *value, GParamSpec *pspec)
{
  TestProvider *self = TEST_PROVIDER (object);

  if (prop_id == PROP_PROVIDER_DISCOVER)
    g_value_set_boolean (value, self->discover);
  else
    G_OBJECT_WARN_INVALID_PROPERTY_ID (object, prop_id, pspec);
}

static void
test_provider_set_property (GObject *object, guint prop_id, const GValue *value, GParamSpec *pspec)
{
  TestProvider *self = TEST_PROVIDER (object);

  if (prop_id == PROP_PROVIDER_DISCOVER)
    self->discover = g_value_get_boolean (value);
  else
    G_OBJECT_WARN_INVALID_PROPERTY_ID (object, prop_id, pspec);
}

static void
test_provider_finalize (GObject *object)
{
  TestProvider *self = TEST_PROVIDER (object);

  g_clear_pointer (&self->sinks, g_ptr_array_unref);

  G_OBJECT_CLASS (test_provider_parent_class)->finalize (object);
}

static void
test_provider_class_init (TestProviderClass *klass)
{
  GObjectClass *object_class = G_OBJECT_CLASS (klass);

  object_class->get_property = test_provider_get_property;
  object_class->set_property = test_provider_set_property;
  object_class->finalize = test_provider_finalize;

  g_object_class_override_property (object_class, PROP_PROVIDER_DISCOVER, "discover");
}

static void
test_provider_init (TestProvider *self)
{
  self->sinks = g_ptr_array_new_with_free_func (g_object_unref);
}

static void
test_provider_announce (TestProvider *self, NdSink *sink)
{
  g_ptr_array_add (self->sinks, g_object_ref (sink));
  g_signal_emit_by_name (self, "sink-added", sink);
}

/* The test itself. */

static void
sink_removed_cb (NdMetaProvider *provider, NdSink *sink, gpointer user_data)
{
  guint *removed = user_data;

  g_autofree gchar *name = NULL;

  /* Touching the sink here is what crashed the daemon. */
  g_assert_true (ND_IS_SINK (sink));

  g_object_get (sink, "display-name", &name, NULL);
  g_assert_nonnull (name);

  *removed += 1;
}

static void
sink_added_cb (NdMetaProvider *provider, NdSink *sink, gpointer user_data)
{
  guint *added = user_data;

  /* The signal is documented to carry the sink that was added. */
  g_assert_true (ND_IS_SINK (sink));

  *added += 1;
}

int
main (void)
{
  g_autoptr(NdMetaProvider) meta = nd_meta_provider_new ();
  g_autoptr(TestProvider) provider = g_object_new (TEST_TYPE_PROVIDER, NULL);
  g_autoptr(NdSink) wfd = NULL;
  g_autoptr(NdSink) cc = NULL;
  g_autoptr(NdSink) both = NULL;
  const gchar *wfd_match[] = { "00:00:5e:00:53:01", NULL };
  const gchar *cc_match[] = { "203.0.113.50", NULL };
  const gchar *both_match[] = { "00:00:5e:00:53:01", "203.0.113.50", NULL };
  guint added = 0, removed = 0;
  GList *sinks = NULL;

  nd_meta_provider_add_provider (meta, ND_PROVIDER (provider));

  g_signal_connect (meta, "sink-added", G_CALLBACK (sink_added_cb), &added);
  g_signal_connect (meta, "sink-removed", G_CALLBACK (sink_removed_cb), &removed);

  /* The same receiver seen over two protocols: two separate meta sinks. */
  wfd = test_sink_new ("Receiver over Wi-Fi Direct", wfd_match);
  cc = test_sink_new ("Receiver over Chromecast", cc_match);
  test_provider_announce (provider, wfd);
  test_provider_announce (provider, cc);
  g_assert_cmpuint (added, ==, 2);

  /* A sink that matches both of them forces the merge. */
  both = test_sink_new ("Receiver, both protocols", both_match);
  test_provider_announce (provider, both);

  g_assert_cmpuint (removed, ==, 1);
  g_assert_cmpuint (added, ==, 3);

  /* One meta sink must remain. */
  sinks = nd_provider_get_sinks (ND_PROVIDER (meta));
  g_assert_cmpuint (g_list_length (sinks), ==, 1);
  g_list_free (sinks);

  return 0;
}
