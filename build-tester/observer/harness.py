import functools, http.server, json, os, socketserver, threading, time

BIN_DEFAULT = "/tmp/cfx_sync4/app/Camoufox.app/Contents/MacOS/camoufox"
SURFACE_NAMES = {1:"canvas",2:"webgl",3:"webrtc",4:"navigator",5:"screen",6:"fonts",7:"audio"}
FIREFOX_WEBGL_PREFS = {"webgl.force-enabled": True, "webgl.enable-webgl2": True,
                       "media.peerconnection.ice.obfuscate_host_addresses": False}

_SNAP_JS = ("try{var {getCollector}=ChromeUtils.importESModule("
            "'resource://gre/modules/TrackingObserver.sys.mjs');var c=getCollector();"
            "return c?JSON.stringify(c.snapshot()):'[]';}catch(e){return 'ERR:'+e;}")
_COOKIE_JS = ("try{let o=[];for(let c of Services.cookies.cookies){o.push({name:c.name,host:c.host});}"
              "return JSON.stringify(o);}catch(e){return 'ERR:'+e;}")

def serve(directory):
    h = functools.partial(http.server.SimpleHTTPRequestHandler, directory=str(directory))
    httpd = socketserver.TCPServer(("127.0.0.1", 0), h)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    return httpd.server_address[1], httpd.shutdown

class Session:
    def __init__(self, camou_config=None, arm=True, binary=None, prefs=None):
        self.camou_config = camou_config
        self.arm = arm
        self.binary = binary or os.environ.get("CFX_BIN", BIN_DEFAULT)
        self.prefs = {**FIREFOX_WEBGL_PREFS, **(prefs or {})}
        self.m = None

    def __enter__(self):
        if self.arm: os.environ["CAMOU_OBSERVE"] = "1"
        else: os.environ.pop("CAMOU_OBSERVE", None)
        if self.camou_config is not None:
            os.environ["CAMOU_CONFIG"] = json.dumps(self.camou_config)
        else:
            os.environ.pop("CAMOU_CONFIG", None)
        from marionette_driver.marionette import Marionette
        self.m = Marionette(bin=self.binary, port=0, headless=True, prefs=self.prefs)
        self.m.start_session()
        return self

    def __exit__(self, *a):
        try: self.m.cleanup()
        except Exception: pass

    def navigate(self, url): self.m.navigate(url)
    def eval_content(self, js): return self.m.execute_script(js)

    def wait_done(self, timeout=30):
        # window.wrappedJSObject: Marionette content-context execute_script Xray-wraps
        # window by default, so plain window.__done__ reads the native-only Xray view
        # and is always undefined for a page-script expando -- verified empirically
        # (window.foo=42 set by page script reads back None via window.foo, 42 via
        # window.wrappedJSObject.foo). See marionette_driver's execute_script docstring.
        for _ in range(int(timeout / 0.3)):
            time.sleep(0.3)
            try:
                if self.m.execute_script("return !!window.wrappedJSObject.__done__;"): return True
            except Exception: pass
        raise TimeoutError(f"window.__done__ not set within {timeout}s")

    def snapshot(self):
        time.sleep(1.2)  # let the observer's 500ms actor drain feed the parent Collector
        with self.m.using_context("chrome"):
            raw = self.m.execute_script(_SNAP_JS)
        if raw.startswith("ERR:"): raise RuntimeError("snapshot: " + raw)
        out = []
        for r in json.loads(raw):
            surfaces = {SURFACE_NAMES.get(int(k), k): v for k, v in r["surfaces"].items()}
            out.append({"site": r["key"]["site"], "surfaces": surfaces, "requests": r.get("requests", [])})
        return out

    def cookies(self):
        with self.m.using_context("chrome"):
            raw = self.m.execute_script(_COOKIE_JS)
        return json.loads(raw) if not raw.startswith("ERR:") else []
