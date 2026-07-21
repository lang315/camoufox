"""Does the window.devicePixelRatio MaskConfig key create a split-brain?
Host is Retina (real dpr=2). Force the key to 1. If the getter reads 1 but
matchMedia still reports 2dppx, the key only patches the JS getter and leaves
the layout/media-query DPI at the host value -> page-verifiable contradiction,
strictly worse than the passthrough leak. This is why WS2 must drive dpr through
the overrideDPPX/device_scale_factor layer, NOT this key. Run headful (headless
forces dpr=1.0 and masks it)."""
import json, os
from marionette_driver.marionette import Marionette
BIN = os.environ.get("CFX_BIN", "/tmp/cfx_sync4/app/Camoufox.app/Contents/MacOS/camoufox")
os.environ["CAMOU_CONFIG"] = json.dumps({"window.devicePixelRatio": 1.0})
m = Marionette(bin=BIN, port=0, headless=False)  # HEADFUL: real host dpr=2
m.start_session()
try:
    m.navigate("data:text/html,<title>s</title>")
    r = json.loads(m.execute_script("""
      return JSON.stringify({
        getter: window.devicePixelRatio,
        mm_1dppx: matchMedia('(resolution: 1dppx)').matches,
        mm_2dppx: matchMedia('(resolution: 2dppx)').matches,
        mm_min15: matchMedia('(min-resolution: 1.5dppx)').matches
      });"""))
    print(json.dumps(r))
    split = (r["getter"] == 1) and (r["mm_2dppx"] is True or r["mm_1dppx"] is False)
    print("SPLIT-BRAIN CONFIRMED (getter=1 but matchMedia=host)" if split
          else "COHERENT (matchMedia tracks the forced getter)")
finally:
    m.cleanup()
