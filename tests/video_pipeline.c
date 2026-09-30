/* The whole video pipeline, configured the way a receiver session configures
 * it, running in real time on a screen-sized moving picture.
 *
 * Checks the settings that keep motion smooth and sharp (patches 0018 to
 * 0024), that the constrained high profile negotiates through the whole
 * pipeline, and that frames get through instead of being dropped. */
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
                              NULL);
  g_object_set (filter, "caps", caps, NULL);
  gst_bin_add_many (GST_BIN (bin), src, filter, NULL);
  g_assert_true (gst_element_link (src, filter));
  pad = gst_element_get_static_pad (filter, "src");
  gst_element_add_pad (bin, gst_ghost_pad_new ("src", pad));

  return g_object_ref_sink (bin);
}

static WfdParams *
receiver_params (WfdH264ProfileFlags profile, guint8 level, gint refresh, gint max_slices)
{
  WfdParams *params = wfd_params_new ();

  params->selected_codec = wfd_video_codec_new ();
  params->selected_codec->profile = profile;
  params->selected_codec->level = level;
  params->selected_codec->max_slice_num = max_slices;
  params->selected_resolution = wfd_resolution_new ();
  params->selected_resolution->width = 1920;
  params->selected_resolution->height = 1080;
  params->selected_resolution->refresh_rate = refresh;
  params->selected_resolution->interlaced = FALSE;

  return params;
}

static gboolean
quit_cb (gpointer loop)
{
  g_main_loop_quit (loop);
  return G_SOURCE_REMOVE;
}

/* Configures a pipeline for @params and returns its encoder. */
static GstElement *
configure (WfdMediaFactory *factory, WfdParams *params, GstElement **bin_out)
{
  GstElement *bin = wfd_media_factory_create_element (GST_RTSP_MEDIA_FACTORY (factory), NULL);

  g_assert_nonnull (bin);
  wfd_configure_media_element (GST_BIN (bin), params);
  *bin_out = bin;

  return gst_bin_get_by_name (GST_BIN (bin), "wfd-encoder");
}

/* Runs a configured pipeline in real time and checks that frames get
 * through. */
static void
run (GstElement *bin, gint refresh, gint seconds)
{
  g_autoptr(GstElement) pipeline = gst_pipeline_new ("video-pipeline-test");
  g_autoptr(GstElement) payloader = gst_bin_get_by_name (GST_BIN (bin), "pay0");
  g_autoptr(GstElement) scale = gst_bin_get_by_name (GST_BIN (bin), "wfd-scale");
  g_autoptr(GstElement) parse = gst_bin_get_by_name (GST_BIN (bin), "wfd-h264parse");
  g_autoptr(GstPad) scale_sink = gst_element_get_static_pad (scale, "sink");
  g_autoptr(GstPad) parsed = gst_element_get_static_pad (parse, "src");
  g_autoptr(GMainLoop) loop = g_main_loop_new (NULL, FALSE);
  GstElement *sink = gst_element_factory_make ("fakesink", NULL);

  /* Where the RTSP server would put its UDP sink. */
  g_object_set (sink, "sync", TRUE, NULL);
  gst_bin_add (GST_BIN (bin), sink);
  g_assert_true (gst_element_link (payloader, sink));

  captured = encoded = 0;
  gst_pad_add_probe (scale_sink, GST_PAD_PROBE_TYPE_BUFFER, count_cb, &captured, NULL);
  gst_pad_add_probe (parsed, GST_PAD_PROBE_TYPE_BUFFER, count_cb, &encoded, NULL);

  gst_bin_add (GST_BIN (pipeline), bin);
  gst_pipeline_set_latency (GST_PIPELINE (pipeline), 80 * GST_MSECOND);
  g_assert_cmpint (gst_element_set_state (pipeline, GST_STATE_PLAYING), !=, GST_STATE_CHANGE_FAILURE);
  g_timeout_add_seconds (seconds, quit_cb, loop);
  g_main_loop_run (loop);
  gst_element_set_state (pipeline, GST_STATE_NULL);

  g_message ("%d Hz: %d frames captured, %d encoded", refresh, captured, encoded);
  g_assert_cmpint (captured, >=, refresh * seconds * 8 / 10);
  /* A couple of frames are still on their way through when it stops. A
   * machine too slow to keep up at all would lose far more. */
  g_assert_cmpint (encoded, >=, captured * 9 / 10);
}

int
main (int argc, char **argv)
{
  g_autoptr(WfdMediaFactory) factory = NULL;
  g_auto(GStrv) missing_video = NULL;
  g_auto(GStrv) missing_audio = NULL;
  guint threads = 0, bitrate = 0, n_threads = 1;
  gboolean sliced = FALSE, cabac = TRUE, dct8x8 = TRUE;

  gst_init (&argc, &argv);
  factory = wfd_media_factory_new ();
  g_assert_true (wfd_media_factory_lookup_encoders (factory, PROFILE_HIGH_H264,
                                                     &missing_video, &missing_audio));
  g_signal_connect (factory, "create-source", G_CALLBACK (create_screen_source), NULL);

  /* Constrained baseline 1080p30, level 4.1, from a receiver taking slices. */
  {
    WfdParams *params = receiver_params (WFD_H264_PROFILE_BASE, 1 << 3, 30, 8);
    GstElement *bin;
    g_autoptr(GstElement) encoder = configure (factory, params, &bin);
    g_autoptr(GstElement) scale = gst_bin_get_by_name (GST_BIN (bin), "wfd-scale");

    g_assert_cmpstr (GST_OBJECT_NAME (gst_element_get_factory (encoder)), ==, "x264enc");
    g_object_get (encoder, "threads", &threads, "sliced-threads", &sliced, "bitrate", &bitrate,
                  "cabac", &cabac, "dct8x8", &dct8x8, NULL);
    g_assert_cmpuint (threads, ==, 4);
    g_assert_true (sliced);
    g_assert_cmpuint (bitrate, ==, 10 * 1024);
    g_assert_false (cabac);
    g_assert_false (dct8x8);
    g_object_get (scale, "n-threads", &n_threads, NULL);
    g_assert_cmpuint (n_threads, ==, 0);

    run (bin, 30, 3);
    wfd_params_free (params);
  }

  /* A receiver that takes one slice per picture gets one. */
  {
    WfdParams *params = receiver_params (WFD_H264_PROFILE_BASE, 1 << 3, 30, 1);
    GstElement *bin;
    g_autoptr(GstElement) encoder = configure (factory, params, &bin);

    g_object_get (encoder, "threads", &threads, "sliced-threads", &sliced, NULL);
    g_assert_cmpuint (threads, ==, 1);
    g_assert_false (sliced);
    gst_object_unref (gst_object_ref_sink (bin));
    wfd_params_free (params);
  }

  /* Constrained high 1080p60, level 4.2: the high profile's own tools, a
   * bitrate limit that grows with the frame rate, and a pipeline that
   * negotiates and keeps up. */
  {
    WfdParams *params = receiver_params (WFD_H264_PROFILE_HIGH, 1 << 4, 60, 8);
    GstElement *bin;
    g_autoptr(GstElement) encoder = configure (factory, params, &bin);

    g_object_get (encoder, "bitrate", &bitrate, "cabac", &cabac, "dct8x8", &dct8x8, NULL);
    g_assert_cmpuint (bitrate, ==, 20 * 1024);
    g_assert_true (cabac);
    g_assert_true (dct8x8);

    run (bin, 60, 3);
    wfd_params_free (params);
  }

  return 0;
}
