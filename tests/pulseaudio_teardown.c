/* Regression test for the PulseAudio teardown abort.
 *
 * Before the fix, finalizing an NdPulseaudio object disconnected the PA
 * context while the state callback was still installed. The callback then
 * left the switch statement through the FAILED/TERMINATED branch, which
 * ran the cleanup handler of a g_autofree variable that had never been
 * initialised, and glibc aborted the process with a heap error.
 */

#include <gio/gio.h>
#include <glib.h>

#include "nd-pulseaudio.h"

typedef struct
{
  GMainLoop *loop;
  gboolean   finished;
  gboolean   success;
} TestState;

static void
init_cb (GObject *source, GAsyncResult *res, gpointer user_data)
{
  TestState *state = user_data;

  g_autoptr(GError) error = NULL;

  state->success = g_async_initable_init_finish (G_ASYNC_INITABLE (source), res, &error);
  if (!state->success)
    g_message ("PulseAudio init failed: %s", error ? error->message : "unknown");

  state->finished = TRUE;
  g_main_loop_quit (state->loop);
}

static gboolean
timeout_cb (gpointer user_data)
{
  TestState *state = user_data;

  g_main_loop_quit (state->loop);

  return G_SOURCE_REMOVE;
}

int
main (void)
{
  gboolean initialised_at_least_once = FALSE;

  for (guint i = 0; i < 3; i++)
    {
      TestState state = { NULL, FALSE, FALSE };
      NdPulseaudio *pulse = nd_pulseaudio_new ("Teardown Regression Sink",
                                               "deadbeefdeadbeef");

      state.loop = g_main_loop_new (NULL, FALSE);

      g_async_initable_init_async (G_ASYNC_INITABLE (pulse),
                                   G_PRIORITY_LOW,
                                   NULL,
                                   init_cb,
                                   &state);

      g_timeout_add_seconds (10, timeout_cb, &state);
      g_main_loop_run (state.loop);

      if (state.success)
        {
          initialised_at_least_once = TRUE;
          nd_pulseaudio_unload (pulse);
        }

      /* This is the path that used to abort. */
      g_object_unref (pulse);

      /* Let any pending idle sources of the finished task run. */
      while (g_main_context_iteration (NULL, FALSE))
        ;

      g_main_loop_unref (state.loop);
    }

  if (!initialised_at_least_once)
    {
      g_message ("No usable PulseAudio server; teardown path still exercised.");
      return 77;
    }

  return 0;
}
