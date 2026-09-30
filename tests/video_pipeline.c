/* The whole video pipeline, configured the way a receiver session configures
 * it, running in real time on a screen-sized moving picture.
 *
 * Checks the settings that keep motion smooth (patches 0018 to 0020) and
 * that frames get through the pipeline instead of being dropped. */
#include <gst/gst.h>

#include "wfd-media-factory.h"
#include "wfd-params.h"

static gint captured;
static gint encoded;

static GstPadProbeReturn
count_cb (GstPad *pad, GstPadProbeInfo *info, gpointer user_data)
{
  g_atomic_int_inc ((gint *) user_data);
  return GST_PAD_PROBE_OK;
}

static GstElement *
create_screen_source (WfdMediaFactory *factory, gpointer user_data)
{
  GstElement *bin = gst_bin_new ("test-screen");
  GstElement *src = gst_element_factory_make ("videotestsrc", NULL);
  GstElement *filter = gst_element_factory_make ("capsfilter", NULL);
  g_autoptr(GstCaps) caps = NULL;
  g_autoptr(GstPad) pad = NULL;

  /* A 16:10 screen scrolling sideways: every pixel changes every frame. */
  g_object_set (src, "is-live", TRUE, "pattern", 0, "horizontal-speed", 12, NULL);
  caps = gst_caps_new_simple ("video/x-raw",
                              "format", G_TYPE_STRING, "BGRA",
                              "width", G_TYPE_INT, 2560,
                              "height", G_TYPE_INT, 1600,
                              "framerate", GST_TYPE_FRACTION, 30, 1,
                              NULL);
  g_object_set (filter, "caps", caps, NULL);
  gst_bin_add_many (GST_BIN (bin), src, filter, NULL);
  g_assert_true (gst_element_link (src, filter));
  pad = gst_element_get_static_pad (filter, "src");
  gst_element_add_pad (bin, gst_ghost_pad_new ("src", pad));
  gst_pad_add_probe (pad, GST_PAD_PROBE_TYPE_BUFFER, count_cb, &captured, NULL);

  return g_object_ref_sink (bin);
}

static gboolean
quit_cb (gpointer loop)
{
  g_main_loop_quit (loop);
  return G_SOURCE_REMOVE;
}

int
main (int argc, char **argv)
{
  g_autoptr(WfdMediaFactory) factory = NULL;
  g_autoptr(GstElement) pipeline = NULL;
  g_autoptr(GstElement) encoder = NULL;
  g_autoptr(GstElement) scale = NULL;
  g_autoptr(GstElement) parse = NULL;
  g_autoptr(GstElement) payloader = NULL;
  g_autoptr(GstPad) parsed = NULL;
  g_auto(GStrv) missing_video = NULL;
  g_auto(GStrv) missing_audio = NULL;
  g_autoptr(GMainLoop) loop = NULL;
  GstElement *bin;
  GstElement *sink;
  WfdParams *params;
  guint threads = 0, bitrate = 0, n_threads = 1;
  gboolean sliced = FALSE;

  gst_init (&argc, &argv);
  factory = wfd_media_factory_new ();
  g_assert_true (wfd_media_factory_lookup_encoders (factory, PROFILE_HIGH_H264,
                                                     &missing_video, &missing_audio));
  g_signal_connect (factory, "create-source", G_CALLBACK (create_screen_source), NULL);

  bin = wfd_media_factory_create_element (GST_RTSP_MEDIA_FACTORY (factory), NULL);
  g_assert_nonnull (bin);

  /* A receiver asking for constrained baseline 1080p30, level 4.1. */
  params = wfd_params_new ();
  params->selected_codec = wfd_video_codec_new ();
  params->selected_codec->profile = WFD_H264_PROFILE_BASE;
  params->selected_codec->level = 1 << 3;
  params->selected_resolution = wfd_resolution_new ();
  params->selected_resolution->width = 1920;
  params->selected_resolution->height = 1080;
  params->selected_resolution->refresh_rate = 30;
  params->selected_resolution->interlaced = FALSE;
  wfd_configure_media_element (GST_BIN (bin), params);

  encoder = gst_bin_get_by_name (GST_BIN (bin), "wfd-encoder");
  g_assert_cmpstr (GST_OBJECT_NAME (gst_element_get_factory (encoder)), ==, "x264enc");
  g_object_get (encoder, "threads", &threads, "sliced-threads", &sliced, "bitrate", &bitrate, NULL);
  g_assert_cmpuint (threads, ==, 4);
  g_assert_true (sliced);
  g_assert_cmpuint (bitrate, ==, 10 * 1024);

  scale = gst_bin_get_by_name (GST_BIN (bin), "wfd-scale");
  g_object_get (scale, "n-threads", &n_threads, NULL);
  g_assert_cmpuint (n_threads, ==, 0);

  /* Where the RTSP server would put its UDP sink. */
  sink = gst_element_factory_make ("fakesink", NULL);
  g_object_set (sink, "sync", TRUE, NULL);
  gst_bin_add (GST_BIN (bin), sink);
  payloader = gst_bin_get_by_name (GST_BIN (bin), "pay0");
  g_assert_true (gst_element_link (payloader, sink));

  parse = gst_bin_get_by_name (GST_BIN (bin), "wfd-h264parse");
  parsed = gst_element_get_static_pad (parse, "src");
  gst_pad_add_probe (parsed, GST_PAD_PROBE_TYPE_BUFFER, count_cb, &encoded, NULL);

  pipeline = gst_pipeline_new ("video-pipeline-test");
  gst_bin_add (GST_BIN (pipeline), bin);
  gst_pipeline_set_latency (GST_PIPELINE (pipeline), 150 * GST_MSECOND);

  loop = g_main_loop_new (NULL, FALSE);
  g_assert_cmpint (gst_element_set_state (pipeline, GST_STATE_PLAYING), !=, GST_STATE_CHANGE_FAILURE);
  g_timeout_add_seconds (5, quit_cb, loop);
  g_main_loop_run (loop);
  gst_element_set_state (pipeline, GST_STATE_NULL);

  g_message ("%d frames captured, %d encoded", captured, encoded);
  g_assert_cmpint (captured, >=, 120);
  /* A couple of frames are still on their way through when it stops. A
   * machine too slow to keep up at all would lose far more. */
  g_assert_cmpint (encoded, >=, captured * 9 / 10);

  wfd_params_free (params);
  return 0;
}
