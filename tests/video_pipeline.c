/* The whole media pipeline, configured the way a receiver session configures
 * it, running in real time on a screen-sized moving picture with sound.
 *
 * Checks the settings that keep motion smooth and sharp (patches 0018 to
 * 0028), that the constrained high profile negotiates through the whole
 * pipeline, that frames get through instead of being dropped, and that whole
 * frames leave evenly, which is what a receiver sees (patch 0027). */
#include <gst/gst.h>
#include <stdlib.h>

#include "wfd-audio-codec.h"
#include "wfd-media-factory.h"
#include "wfd-params.h"

static gint captured;
static gint encoded;

/* When the last packet of each frame left the pipeline, from the RTP stream at
 * the sink: a frame is complete when the next one starts. */
static GArray *completions;
static gdouble last_video_packet = -1;

static void
sink_handoff_cb (GstElement *sink, GstBuffer *buffer, GstPad *pad, gpointer user_data)
{
  g_autoptr(GstClock) clock = gst_element_get_clock (sink);
  gdouble now = clock ? (gst_clock_get_time (clock) - gst_element_get_base_time (sink)) / 1e9 : 0;
  GstMapInfo map;

  if (!gst_buffer_map (buffer, &map, GST_MAP_READ))
    return;

  /* The RTP header is 12 bytes, then 188-byte TS packets. */
  for (gsize offset = 12; offset + 188 <= map.size; offset += 188)
    {
      const guint8 *packet = map.data + offset;
      gint pid = ((packet[1] & 0x1f) << 8) | packet[2];

      if (packet[0] != 0x47 || pid != 0x1011)
        continue;
      if ((packet[1] & 0x40) && last_video_packet >= 0)
        g_array_append_val (completions, last_video_packet);
      last_video_packet = now;
    }

  gst_buffer_unmap (buffer, &map);
}

static gint
compare_doubles (gconstpointer a, gconstpointer b)
{
  gdouble x = *(const gdouble *) a, y = *(const gdouble *) b;

  return (x > y) - (x < y);
}

/* A live sound source that delivers 40 ms at a time, like the capture of the
 * desktop's sound. */
static GstElement *
create_sound_source (WfdMediaFactory *factory, gpointer user_data)
{
  GstElement *src = gst_element_factory_make ("audiotestsrc", NULL);

  g_object_set (src, "is-live", TRUE, "samplesperbuffer", 1920, "wave", 8, NULL);

  return g_object_ref_sink (src);
}

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
  params->selected_audio_codec = wfd_audio_codec_new ();
  params->selected_audio_codec->type = WFD_AUDIO_AAC;
  params->selected_audio_codec->modes = 0x1;

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
  /* The latency wfd_media_factory_create_pipeline() gives x264, unless a
   * different one is being tried. */
  const gchar *latency_override = g_getenv ("MIRDISPO_TEST_LATENCY_MS");
  gint latency_ms = latency_override ? atoi (latency_override) : 120;
  GArray *gaps;

  /* Where the RTSP server would put its UDP sink. */
  g_object_set (sink, "sync", TRUE, "signal-handoffs", TRUE, NULL);
  g_signal_connect (sink, "handoff", G_CALLBACK (sink_handoff_cb), NULL);
  completions = g_array_new (FALSE, FALSE, sizeof (gdouble));
  last_video_packet = -1;
  gst_bin_add (GST_BIN (bin), sink);
  g_assert_true (gst_element_link (payloader, sink));

  captured = encoded = 0;
  gst_pad_add_probe (scale_sink, GST_PAD_PROBE_TYPE_BUFFER, count_cb, &captured, NULL);
  gst_pad_add_probe (parsed, GST_PAD_PROBE_TYPE_BUFFER, count_cb, &encoded, NULL);

  gst_bin_add (GST_BIN (pipeline), bin);
  gst_pipeline_set_latency (GST_PIPELINE (pipeline), latency_ms * GST_MSECOND);
  g_assert_cmpint (gst_element_set_state (pipeline, GST_STATE_PLAYING), !=, GST_STATE_CHANGE_FAILURE);
  g_timeout_add_seconds (seconds, quit_cb, loop);
  g_main_loop_run (loop);
  gst_element_set_state (pipeline, GST_STATE_NULL);

  g_message ("%d Hz: %d frames captured, %d encoded", refresh, captured, encoded);
  g_assert_cmpint (captured, >=, refresh * seconds * 8 / 10);
  /* A couple of frames are still on their way through when it stops. A
   * machine too slow to keep up at all would lose far more. */
  g_assert_cmpint (encoded, >=, captured * 9 / 10);

  /* Whole frames leave at the frame rate. With too short a latency the last
   * packets of a frame leave whenever the muxer releases them, and the
   * receiver gets frames at uneven intervals. The first second is left out
   * while the pipeline settles. */
  gaps = g_array_new (FALSE, FALSE, sizeof (gdouble));
  for (guint i = 1; i < completions->len; i++)
    {
      gdouble at = g_array_index (completions, gdouble, i);
      gdouble gap = (at - g_array_index (completions, gdouble, i - 1)) * 1000;

      if (at > 1.0)
        g_array_append_val (gaps, gap);
    }
  g_array_sort (gaps, compare_doubles);
  g_assert_cmpuint (gaps->len, >, 10);
  {
    gdouble frame = 1000.0 / refresh;
    gdouble p5 = g_array_index (gaps, gdouble, gaps->len * 5 / 100);
    gdouble p95 = g_array_index (gaps, gdouble, gaps->len * 95 / 100);

    g_message ("%d Hz at %d ms: frames complete %.1f to %.1f ms apart (5th to 95th percentile)",
               refresh, latency_ms, p5, p95);
    g_assert_cmpfloat (p5, >, frame * 0.6);
    g_assert_cmpfloat (p95, <, frame * 1.4);
  }
  g_array_unref (gaps);
  g_array_unref (completions);
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
  g_signal_connect (factory, "create-audio-source", G_CALLBACK (create_sound_source), NULL);

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
    /* Constant quality held under that bitrate, not a constant quantizer
     * that ignores it (patch 0026). */
    {
      gint pass = 0;

      g_object_get (encoder, "pass", &pass, NULL);
      g_assert_cmpint (pass, ==, 5);
    }
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
