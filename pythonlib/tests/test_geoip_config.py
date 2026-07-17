"""Regression tests for #589: geoip=True must not override an explicit user
timezone/locale, but must still fill those (and all other geo keys) when the
user left them unset."""

from camoufox.utils import merge_geo_config


def test_geoip_respects_user_timezone_and_locale_override():
    # User explicitly set timezone + language; geoip guessed different values.
    config = {'timezone': 'America/Phoenix', 'locale:language': 'es'}
    geo = {
        'timezone': 'America/Chicago',       # wrong geoip guess — must be ignored
        'locale:language': 'en',             # user set 'es' — must be ignored
        'locale:region': 'US',               # user unset — geoip fills
        'geolocation:latitude': 33.4,        # non-override key — always from geoip
        'geolocation:longitude': -112.0,
    }
    merge_geo_config(config, geo)

    assert config['timezone'] == 'America/Phoenix'   # user wins (#589)
    assert config['locale:language'] == 'es'         # user wins (#589)
    assert config['locale:region'] == 'US'           # geoip fills unset override key
    assert config['geolocation:latitude'] == 33.4    # geoip sets non-override key
    assert config['geolocation:longitude'] == -112.0


def test_geoip_fills_timezone_when_user_unset():
    config = {}
    merge_geo_config(config, {'timezone': 'America/Chicago', 'locale:region': 'US'})
    assert config['timezone'] == 'America/Chicago'   # geoip fills when user unset
    assert config['locale:region'] == 'US'


def test_geoip_overwrites_non_override_keys_even_if_present():
    # Non-timezone/locale geo keys are always taken from geoip (unconditional set).
    config = {'geolocation:latitude': 0.0}
    merge_geo_config(config, {'geolocation:latitude': 51.5})
    assert config['geolocation:latitude'] == 51.5
