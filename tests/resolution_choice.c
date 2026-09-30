/* The mode sent to a receiver is the best one it says it supports.
 *
 * Ranked by resolution first and refresh rate as the tie-break, which is
 * this project's existing ordering. Choosing between a sharper picture and
 * a smoother one on the user's behalf would be guesswork: which is better
 * depends on the room, the screen and what is being shown. What the receiver
 * advertises is a fact, and that is what decides.
 */

#include <glib.h>

#include "wfd-client.h"
#include "wfd-video-codec.h"
#include "wfd-resolution.h"

static GList *
modes (const gint table[][4], gsize count)
{
  GList *res = NULL;

  for (gsize i = 0; i < count; i++)
    {
      WfdResolution *r = wfd_resolution_new ();

      r->width = table[i][0];
      r->height = table[i][1];
      r->refresh_rate = table[i][2];
      r->interlaced = table[i][3];
      res = g_list_append (res, r);
    }

  return res;
}

int
main (void)
{
  /* Exactly what one receiver offered, in the order it offered it. */
  static const gint advertised[][4] = {
    {800, 480, 30, 0}, {854, 480, 30, 0}, {864, 480, 30, 0}, {640, 360, 30, 0},
    {960, 540, 30, 0}, {848, 480, 30, 0}, {640, 480, 60, 0}, {720, 480, 60, 0},
    {720, 480, 60, 1}, {720, 576, 50, 0}, {720, 576, 50, 1}, {1280, 720, 30, 0},
    {1280, 720, 60, 0}, {1920, 1080, 30, 0}, {1290, 720, 25, 0},
    {1920, 1080, 25, 0}, {1280, 720, 24, 0}, {800, 600, 30, 0},
    {800, 600, 60, 0}, {1024, 768, 30, 0}, {1024, 768, 60, 0},
    {1152, 864, 30, 0}, {1280, 768, 30, 0}, {1280, 768, 60, 0},
    {1280, 800, 30, 0}, {1360, 768, 30, 0}, {1366, 768, 30, 0},
    {1366, 768, 60, 0}, {1280, 1024, 30, 0}, {1400, 1050, 30, 0},
    {1440, 900, 30, 0}, {1600, 900, 30, 0}, {1600, 1200, 30, 0},
    {1680, 1024, 30, 0}, {1680, 1050, 30, 0}, {1920, 1200, 30, 0},
  };
  static const gint only_slow[][4] = {
    {1280, 720, 30, 0}, {1920, 1080, 30, 0}, {1024, 768, 30, 0},
  };
  static const gint interlaced_only[][4] = {
    {1920, 1080, 60, 1}, {720, 480, 60, 1},
  };

  {
    g_autolist(WfdResolution) list = modes (advertised, G_N_ELEMENTS (advertised));
    WfdResolution *picked = wfd_client_pick_resolution (list, 0, 0);

    g_assert_nonnull (picked);
    /* The largest progressive mode in the list. */
    g_assert_cmpint (picked->width, ==, 1920);
    g_assert_cmpint (picked->height, ==, 1200);
    g_assert_cmpint (picked->refresh_rate, ==, 30);
  }

  {
    g_autolist(WfdResolution) list = modes (only_slow, G_N_ELEMENTS (only_slow));
    WfdResolution *picked = wfd_client_pick_resolution (list, 0, 0);

    g_assert_nonnull (picked);
    g_assert_cmpint (picked->width, ==, 1920);
    g_assert_cmpint (picked->refresh_rate, ==, 30);
  }

  {
    /* Same size, different rates: the faster one wins the tie-break. */
    static const gint same_size[][4] = {
      {1280, 720, 30, 0}, {1280, 720, 60, 0}, {1280, 720, 24, 0},
    };
    g_autolist(WfdResolution) list = modes (same_size, G_N_ELEMENTS (same_size));
    WfdResolution *picked = wfd_client_pick_resolution (list, 0, 0);

    g_assert_nonnull (picked);
    g_assert_cmpint (picked->refresh_rate, ==, 60);
  }

  {
    /* Interlaced modes are not usable, so nothing is chosen and the caller
     * falls back. */
    g_autolist(WfdResolution) list = modes (interlaced_only, G_N_ELEMENTS (interlaced_only));

    g_assert_null (wfd_client_pick_resolution (list, 0, 0));
  }

  {
    g_assert_null (wfd_client_pick_resolution (NULL, 0, 0));
  }

  {
    /* A receiver advertising both tables is a television telling us which
     * timings it is built for. Taking the largest mode across both sent it
     * a computer monitor shape, which showed as the picture flashing.
     */
    g_autoptr(WfdVideoCodec) codec = wfd_video_codec_new ();

    g_autoptr(GList) cea = NULL;
    g_autoptr(GList) everything = NULL;
    WfdResolution *from_cea;
    WfdResolution *from_all;

    codec->cea_sup = 0xffffffff;
    codec->vesa_sup = 0xffffffff;
    codec->hh_sup = 0;

    cea = wfd_video_codec_get_resolutions_cea (codec);
    everything = wfd_video_codec_get_resolutions (codec);

    g_assert_nonnull (cea);
    g_assert_cmpuint (g_list_length (cea), <, g_list_length (everything));

    /* 1920x1200 is a computer monitor shape and belongs to the VESA table
     * alone. Sending it to a television is what made the picture flash, so
     * it must not appear among the modes a television advertises. */
    for (GList *item = cea; item; item = item->next)
      {
        WfdResolution *mode = (WfdResolution *) item->data;

        g_assert_false (mode->width == 1920 && mode->height == 1200);
      }

    {
      gboolean monitor_shape_in_combined = FALSE;

      for (GList *item = everything; item; item = item->next)
        {
          WfdResolution *mode = (WfdResolution *) item->data;

          if (mode->width == 1920 && mode->height == 1200)
            monitor_shape_in_combined = TRUE;
        }

      g_assert_true (monitor_shape_in_combined);
    }

    from_cea = wfd_client_pick_resolution (cea, 0, 0);
    from_all = wfd_client_pick_resolution (everything, 0, 0);

    g_assert_nonnull (from_cea);
    g_assert_nonnull (from_all);
  }

  {
    /* Both ends decide. A laptop sharing a 16:10 screen should not be sent a
     * mode with more pixels than it has, and among what fits, the shape
     * closest to its own avoids black bars or stretching.
     */
    static const gint wide_and_tall[][4] = {
      {3840, 2160, 30, 0},   /* larger than the source */
      {1920, 1080, 30, 0},   /* fits, 16:9 */
      {1680, 1050, 30, 0},   /* fits, 16:10 like the source */
      {1280, 720, 60, 0},    /* fits, 16:9, smaller */
    };
    g_autolist(WfdResolution) list = modes (wide_and_tall, G_N_ELEMENTS (wide_and_tall));
    WfdResolution *picked = wfd_client_pick_resolution (list, 1920, 1200);

    g_assert_nonnull (picked);
    /* 1680x1050 is the same shape as the source, but 1920x1080 shows more of
     * it: the picture fits to 1728x1080 there against 1680x1050 here. */
    g_assert_cmpint (picked->width, ==, 1920);
    g_assert_cmpint (picked->height, ==, 1080);
  }

  {
    /* Shape still matters when it costs enough. A 4:3 source loses a third
     * of a widescreen mode to black bars, so the smaller 4:3 mode shows
     * more of it. */
    static const gint mixed_shapes[][4] = {
      {1920, 1080, 30, 0}, {1600, 1200, 30, 0},
    };
    g_autolist(WfdResolution) list = modes (mixed_shapes, G_N_ELEMENTS (mixed_shapes));
    WfdResolution *picked = wfd_client_pick_resolution (list, 1600, 1200);

    g_assert_nonnull (picked);
    g_assert_cmpint (picked->width, ==, 1600);
    g_assert_cmpint (picked->height, ==, 1200);
  }

  {
    /* A small source is not sent more pixels than it has. */
    static const gint big_modes[][4] = {
      {1920, 1080, 30, 0}, {1280, 720, 60, 0}, {1024, 768, 60, 0},
    };
    g_autolist(WfdResolution) list = modes (big_modes, G_N_ELEMENTS (big_modes));
    WfdResolution *picked = wfd_client_pick_resolution (list, 1366, 768);

    g_assert_nonnull (picked);
    g_assert_cmpint (picked->width, ==, 1280);
    g_assert_cmpint (picked->height, ==, 720);
  }

  {
    /* Every mode larger than the source: send something rather than nothing. */
    static const gint all_big[][4] = {
      {1920, 1080, 30, 0}, {3840, 2160, 30, 0},
    };
    g_autolist(WfdResolution) list = modes (all_big, G_N_ELEMENTS (all_big));
    WfdResolution *picked = wfd_client_pick_resolution (list, 800, 600);

    g_assert_nonnull (picked);
  }

  return 0;
}
