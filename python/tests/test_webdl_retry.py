"""webdl() retries a download the host failed transiently (#242, #421).

A GitHub 5xx once failed the whole fpgen model install in CI. The retry covers
connection errors, 429 and 5xx; any other 4xx is an answer and is raised at once.
GeoIP databases download through webdl() too. Three 504s in 14 s outlasted the
first budget of two retries (#421), so it now spans about 75 s.
"""

import time
from io import BytesIO

import pytest
import requests

from camoufox import pkgman
from camoufox.pkgman import webdl

URL = 'https://example.test/model.zip'


class Reply:
    def __init__(self, status: int, body: bytes = b''):
        self.status_code = status
        self.headers = {'content-length': str(len(body))}
        self._body = body
        self.closed = False

    def raise_for_status(self):
        if self.status_code >= 400:
            raise requests.HTTPError(f'{self.status_code} for url: {URL}')

    def iter_content(self, size):
        yield self._body

    def close(self):
        self.closed = True


@pytest.fixture
def script(monkeypatch):
    """Serve the given outcomes in order; an Exception is raised, a Reply returned."""
    calls = []
    sleeps = []

    def serve(*outcomes):
        queue = list(outcomes)

        def get(url, **kw):
            calls.append(url)
            outcome = queue.pop(0)
            if isinstance(outcome, Exception):
                raise outcome
            return outcome

        monkeypatch.setattr(pkgman.requests, 'get', get)
        monkeypatch.setattr(time, 'sleep', sleeps.append)
        return calls, sleeps

    return serve


def fetch() -> bytes:
    return webdl(URL, bar=False, buffer=BytesIO()).read()


@pytest.mark.parametrize('status', [429, 500, 502, 503, 504])
def test_transient_status_is_retried(script, status):
    calls, sleeps = script(Reply(status), Reply(200, b'model'))
    assert fetch() == b'model'
    assert len(calls) == 2
    assert sleeps == [5]


def test_an_outage_of_four_answers_is_ridden_out(script):
    calls, sleeps = script(*[Reply(504)] * 4, Reply(200, b'model'))
    assert fetch() == b'model'
    assert len(calls) == 5
    assert sleeps == [5, 10, 20, 40]


def test_connection_error_is_retried(script):
    calls, _ = script(requests.ConnectionError('reset'), Reply(200, b'model'))
    assert fetch() == b'model'
    assert len(calls) == 2


def test_gives_up_after_the_last_delay_and_raises_the_status(script):
    calls, sleeps = script(*[Reply(500)] * 5)
    with pytest.raises(requests.HTTPError, match='500'):
        fetch()
    assert len(calls) == 5
    assert sleeps == [5, 10, 20, 40]


def test_connection_error_surfaces_after_the_last_delay(script):
    err = requests.ConnectionError('refused')
    calls, _ = script(*[err] * 5)
    with pytest.raises(requests.ConnectionError):
        fetch()
    assert len(calls) == 5


@pytest.mark.parametrize('status', [401, 403, 404])
def test_client_error_is_not_retried(script, status):
    calls, sleeps = script(Reply(status))
    with pytest.raises(requests.HTTPError, match=str(status)):
        fetch()
    assert len(calls) == 1
    assert sleeps == []
