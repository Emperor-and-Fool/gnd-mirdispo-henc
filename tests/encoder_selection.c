#include <gst/gst.h>

#include "wfd-media-factory.h"

static GstElement *
create_test_source (WfdMediaFactory *factory, gpointer user_data)
{
  GstElement *source;

  (void) factory;
  (void) user_data;
  source = gst_element_factory_make ("videotestsrc", NULL);
  gst_object_ref_sink (source);
  return gst_object_ref (source);
}

int
main (int argc, char **argv)
{
  g_autoptr(WfdMediaFactory) factory = NULL;
  g_autoptr(GstElement) pipeline = NULL;
  g_autoptr(GstElement) encoder = NULL;
  g_auto(GStrv) missing_video = NULL;
  g_auto(GStrv) missing_audio = NULL;
  GstElementFactory *element_factory;

  gst_init (&argc, &argv);
  factory = wfd_media_factory_new ();

  g_assert_true (wfd_media_factory_lookup_encoders (factory,
                                                     PROFILE_HIGH_H264,
                                                     &missing_video,
                                                     &missing_audio));

  g_signal_connect (factory,
                    "create-source",
                    G_CALLBACK (create_test_source),
                    NULL);
  pipeline = gst_pipeline_new ("encoder-selection-test");
  g_assert_nonnull (wfd_media_factory_create_video_element (factory,
                                                             GST_BIN (pipeline)));

  encoder = gst_bin_get_by_name (GST_BIN (pipeline), "wfd-encoder");
  g_assert_nonnull (encoder);
  element_factory = gst_element_get_factory (encoder);
  g_assert_nonnull (element_factory);

  /* Software encoding, even where hardware encoding exists.
   *
   * Stopping a cast aborted inside the VA-API media driver, in a free()
   * reached from vaTerminate() as GStreamer released the VA context. That
   * was once blamed on heap corruption elsewhere in this project, which did
   * exist and was fixed; hardware encoding was restored and the same abort
   * returned with the fault entirely inside the driver. */
  g_assert_cmpstr (gst_plugin_feature_get_name (GST_PLUGIN_FEATURE (element_factory)),
                   ==,
                   "x264enc");

  return 0;
}
