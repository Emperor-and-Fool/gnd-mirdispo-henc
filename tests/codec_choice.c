/* Which of a receiver's codec entries is used.
 *
 * A receiver lists the modes it decodes per H.264 profile. Televisions can
 * take 1080p at 60 Hz in the constrained high profile while their
 * constrained baseline entry stops at 30 Hz, so the higher profile is used
 * when it shows the source better and the encoder can produce it. */
#include <glib.h>

#include "wfd-client.h"
#include "wfd-video-codec.h"

/* Constrained baseline, level 4.1, CEA modes up to 1080p30. */
#define BASELINE_1080P30 "01 08 000094FF 00000000 00000000 00 0000 0000 00 none none"
/* Constrained high, level 4.2, CEA modes including 1080p60. */
#define HIGH_1080P60     "02 10 0001FFFF 00000000 00000000 00 0000 0000 00 none none"
/* Constrained high offering nothing baseline does not. */
#define HIGH_1080P30     "02 10 000094FF 00000000 00000000 00 0000 0000 00 none none"

static GPtrArray *
receiver (const gchar *first, ...)
{
  GPtrArray *codecs = g_ptr_array_new_with_free_func ((GDestroyNotify) wfd_video_codec_unref);
  va_list args;

  va_start (args, first);
  for (const gchar *descriptor = first; descriptor; descriptor = va_arg (args, const gchar *))
    g_ptr_array_add (codecs, wfd_video_codec_new_from_desc (0, descriptor));
  va_end (args);

  return codecs;
}

static void
check (GPtrArray *codecs, gboolean high_possible, gint width, gint height,
       WfdH264ProfileFlags profile, gint mode_width, gint mode_height, gint refresh)
{
  WfdResolution *mode = NULL;
  WfdVideoCodec *codec = wfd_client_choose_codec (codecs, high_possible, width, height, &mode);

  g_assert_nonnull (codec);
  g_assert_nonnull (mode);
  g_assert_cmpint (codec->profile, ==, profile);
  g_assert_cmpint (mode->width, ==, mode_width);
  g_assert_cmpint (mode->height, ==, mode_height);
  g_assert_cmpint (mode->refresh_rate, ==, refresh);
}

int
main (void)
{
  g_autoptr(GPtrArray) both = receiver (BASELINE_1080P30, HIGH_1080P60, NULL);
  g_autoptr(GPtrArray) high_first = receiver (HIGH_1080P60, BASELINE_1080P30, NULL);
  g_autoptr(GPtrArray) same = receiver (BASELINE_1080P30, HIGH_1080P30, NULL);
  g_autoptr(GPtrArray) high_only = receiver (HIGH_1080P60, NULL);
  g_autoptr(GPtrArray) baseline_only = receiver (BASELINE_1080P30, NULL);

  /* The high profile gives 1080p60, so it is used. */
  check (both, TRUE, 0, 0, WFD_H264_PROFILE_HIGH, 1920, 1080, 60);
  check (high_first, TRUE, 0, 0, WFD_H264_PROFILE_HIGH, 1920, 1080, 60);
  /* The same with the size of a 16:10 laptop screen being shared: 1920x1080
   * shows as much of it in both profiles, and 60 Hz beats 30 Hz. */
  check (both, TRUE, 2560, 1600, WFD_H264_PROFILE_HIGH, 1920, 1080, 60);

  /* An encoder limited to baseline keeps to the baseline entry. */
  check (both, FALSE, 0, 0, WFD_H264_PROFILE_BASE, 1920, 1080, 30);
  check (high_first, FALSE, 0, 0, WFD_H264_PROFILE_BASE, 1920, 1080, 30);

  /* A high entry that offers nothing better leaves baseline in use. */
  check (same, TRUE, 0, 0, WFD_H264_PROFILE_BASE, 1920, 1080, 30);

  /* With nothing else offered, the only entry is used. */
  check (high_only, FALSE, 0, 0, WFD_H264_PROFILE_HIGH, 1920, 1080, 60);
  check (baseline_only, TRUE, 0, 0, WFD_H264_PROFILE_BASE, 1920, 1080, 30);

  return 0;
}
