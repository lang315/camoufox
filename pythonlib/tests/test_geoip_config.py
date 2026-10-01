"""Regression tests for #589: geoip=True must not override an explicit user
timezone/locale, but must still fill those (and all other geo keys) when the
user left them unset. The merge is inline in launch_options()."""

from types import SimpleNamespace

from camoufox import utils

GEO = {
    'timezone': 'America/Chicago',
    'locale:language': 'en',
    'locale:region': 'US',
    'geolocation:latitude': 33.4,
    'geolocation:longitude': -112.0,
}


def _launch(monkeypatch, config):
    monkeypatch.setattr(utils, 'geoip_allowed', lambda: None)
    monkeypatch.setattr(
        utils, 'get_geolocation', lambda *a, **k: SimpleNamespace(as_config=lambda: dict(GEO))
    )
    opts = utils.launch_options(
        config=config, geoip='203.0.113.7', os='linux', headless=True, i_know_what_im_doing=True
    )
    env = opts['env']
    chunks = sorted((int(k.rsplit('_', 1)[1]), v) for k, v in env.items() if k.startswith('CAMOU_CONFIG_'))
    import orjson

    return orjson.loads(''.join(v for _, v in chunks))


def test_geoip_respects_user_timezone_and_locale_override(monkeypatch):
    cfg = _launch(monkeypatch, {'timezone': 'America/Phoenix', 'locale:language': 'es'})

    assert cfg['timezone'] == 'America/Phoenix'   # user wins (#589)
    assert cfg['locale:language'] == 'es'         # user wins (#589)
    assert cfg['locale:region'] == 'US'           # geoip fills an unset override key
    assert cfg['geolocation:latitude'] == 33.4    # non-override key: always from geoip
    assert cfg['geolocation:longitude'] == -112.0


def test_geoip_fills_timezone_when_user_unset(monkeypatch):
    cfg = _launch(monkeypatch, {})
    assert cfg['timezone'] == 'America/Chicago'
    assert cfg['locale:region'] == 'US'


def test_geoip_overwrites_non_override_keys_even_if_present(monkeypatch):
    cfg = _launch(monkeypatch, {'geolocation:latitude': 0.0})
    assert cfg['geolocation:latitude'] == 33.4
