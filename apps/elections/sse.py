"""
ElectON v2 — Server-Sent Events (SSE) stream views.

Provides two authenticated SSE endpoints:

* ``ElectionSSEView``  — per-election stream for dashboard viewers.
* ``UserSSEView``      — per-user stream for admin-home viewers.

Security
--------
Both views inherit Django's session-based authentication via
``ElectionOwnerMixin`` / ``LoginRequiredMixin``.  No sensitive PII
is transmitted — only aggregate stats and state transitions.

Protocol
--------
Uses ``StreamingHttpResponse`` with ``text/event-stream`` content type.
A keepalive comment (``: keepalive``) is sent every ``SSE_HEARTBEAT_INTERVAL``
seconds to prevent proxy timeouts.  The connection is closed after
``SSE_MAX_CONNECTION_TIME`` seconds; ``EventSource`` reconnects automatically.
"""
import json
import logging
import time

from django.conf import settings
from django.contrib.auth.mixins import LoginRequiredMixin
from django.http import StreamingHttpResponse
from django.views import View

from .mixins import ElectionOwnerMixin

logger = logging.getLogger('electon.sse')


class ElectionSSEView(ElectionOwnerMixin, View):
    """GET /elections/<uuid>/stream/ — per-election real-time event stream."""

    def get(self, request, election_uuid):
        election = self.get_election(election_uuid)
        channel = f'sse:election:{election.election_uuid}'
        response = StreamingHttpResponse(
            _event_stream(channel),
            content_type='text/event-stream',
        )
        response['Cache-Control'] = 'no-cache'
        response['X-Accel-Buffering'] = 'no'  # Disable nginx buffering
        return response


class UserSSEView(LoginRequiredMixin, View):
    """GET /elections/user-stream/ — per-user cross-election event stream."""

    def get(self, request):
        channel = f'sse:user:{request.user.pk}'
        response = StreamingHttpResponse(
            _event_stream(channel),
            content_type='text/event-stream',
        )
        response['Cache-Control'] = 'no-cache'
        response['X-Accel-Buffering'] = 'no'
        return response


# ------------------------------------------------------------------
# Internal generator
# ------------------------------------------------------------------

def _event_stream(channel):
    """Subscribe to *channel* and yield SSE-formatted messages."""
    try:
        import redis as redis_lib
    except ImportError:
        logger.error('redis package not installed — SSE unavailable')
        return

    heartbeat = getattr(settings, 'SSE_HEARTBEAT_INTERVAL', 25)
    max_time = getattr(settings, 'SSE_MAX_CONNECTION_TIME', 3600)

    url = getattr(settings, 'CELERY_BROKER_URL', 'redis://localhost:6379/0')

    try:
        r = redis_lib.from_url(url)
        pubsub = r.pubsub()
        pubsub.subscribe(channel)
    except Exception:
        logger.warning('SSE: could not connect to Redis — stream unavailable', exc_info=True)
        return

    # Send an immediate comment so the browser EventSource transitions
    # out of CONNECTING state without waiting for the first heartbeat.
    yield b': connected\n\n'

    start = time.time()
    last_heartbeat = time.time()

    try:
        while time.time() - start < max_time:
            try:
                message = pubsub.get_message(timeout=1.0)
            except Exception:
                # Redis connection dropped — end stream; client will reconnect
                logger.warning('SSE: Redis connection lost on channel %s', channel)
                break

            if message and message['type'] == 'message':
                data = message['data']
                if isinstance(data, bytes):
                    data = data.decode('utf-8')
                try:
                    parsed = json.loads(data)
                    event_type = parsed.get('type', 'message')
                    yield f'event: {event_type}\ndata: {data}\n\n'.encode('utf-8')
                except (json.JSONDecodeError, ValueError):
                    yield f'data: {data}\n\n'.encode('utf-8')
                last_heartbeat = time.time()

            # Keepalive to prevent proxy / browser timeout
            if time.time() - last_heartbeat >= heartbeat:
                yield b': keepalive\n\n'
                last_heartbeat = time.time()
    except GeneratorExit:
        pass
    finally:
        try:
            pubsub.unsubscribe(channel)
            pubsub.close()
        except Exception:
            pass
