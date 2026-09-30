/* Regression test for the Chromecast teardown recursion.
 *
 * When the TLS session to a receiver dies, closing the control connection
 * calls the sink's end_stream callback, which tears the stream down and
 * sends a disconnect message. That write fails on a dead session and lands
 * back in cc_ctrl_close_connection().
 *
 * The "avoid multiple calls" guard only works if the error state is set
 * before the callback runs. It used to be set afterwards, so the recursion
 * was unbounded and the stream process died of a stack overflow instead of
 * reporting the error.
 */

#include <glib.h>

#include "cc-ctrl.h"

/* Declared in cc-ctrl.c; it is the entry point the comm layer uses. */
void cc_ctrl_error_close_connection_cb (gpointer userdata, GError *error);

static CcCtrl ctrl;
static guint  end_stream_calls;

static void
end_stream_cb (gpointer userdata, GError *error)
{
  end_stream_calls += 1;

  /* Guard the test itself against hanging the machine if the recursion
   * ever comes back. */
  g_assert_cmpuint (end_stream_calls, <, 100);

  /* This models cc_ctrl_finish() failing to send its disconnect message. */
  cc_ctrl_error_close_connection_cb (&ctrl, error);
}

int
main (void)
{
  CcCtrlClosure closure = { NULL, end_stream_cb };

  g_autoptr(GError) error = g_error_new (g_quark_from_static_string ("cc-test"),
                                         1,
                                         "Failed to send the disconnect message");

  ctrl.closure = &closure;

  cc_ctrl_error_close_connection_cb (&ctrl, error);

  /* The re-entrant call must be refused, not followed. */
  g_assert_cmpuint (end_stream_calls, ==, 1);

  return 0;
}
