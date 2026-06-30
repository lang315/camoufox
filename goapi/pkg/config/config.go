// Package config models the CAMOU_CONFIG payload consumed by the
// patched Firefox via additions/camoucfg/MaskConfig.hpp.
//
// The full key set is defined in settings/properties.json. Both
// dot-separated (navigator.*) and colon-separated (canvas:seed,
// webGl:vendor) names are kept verbatim so we can serialize them
// back exactly the way the C++ parser expects.
//
// The serialized form (after JSON marshalling) is split into
// CAMOU_CONFIG_1, CAMOU_CONFIG_2, ... environment variables according
// to platform-specific size limits — see EnvVars.
package config

// Voice mirrors @VOICE_TYPE in settings/camoucfg.jvv.
type Voice struct {
	VoiceURI       string `json:"voiceURI"`
	Name           string `json:"name"`
	Lang           string `json:"lang"`
	IsLocalService bool   `json:"isLocalService"`
	IsDefault      bool   `json:"isDefault"`
}

// MediaDecodeInfo is a spoofed mediaCapabilities.decodingInfo() result for one
// codec, read by MaskConfig::GetMediaDecodingInfo.
type MediaDecodeInfo struct {
	Supported      bool `json:"supported"`
	Smooth         bool `json:"smooth"`
	PowerEfficient bool `json:"powerEfficient"`
}

// Config holds every CAMOU_CONFIG key recognized by Camoufox.
//
// All fields are pointers or omitempty so unset keys are not emitted —
// the C++ side falls back to native Firefox behavior when a key is
// absent.
type Config struct {
	// navigator.*
	NavigatorUserAgent            string   `json:"navigator.userAgent,omitempty"`
	NavigatorDoNotTrack           string   `json:"navigator.doNotTrack,omitempty"`
	NavigatorAppCodeName          string   `json:"navigator.appCodeName,omitempty"`
	NavigatorAppName              string   `json:"navigator.appName,omitempty"`
	NavigatorAppVersion           string   `json:"navigator.appVersion,omitempty"`
	NavigatorOscpu                string   `json:"navigator.oscpu,omitempty"`
	NavigatorLanguage             string   `json:"navigator.language,omitempty"`
	NavigatorLanguages            []string `json:"navigator.languages,omitempty"`
	NavigatorPlatform             string   `json:"navigator.platform,omitempty"`
	NavigatorHardwareConcurrency  *uint32  `json:"navigator.hardwareConcurrency,omitempty"`
	NavigatorProduct              string   `json:"navigator.product,omitempty"`
	NavigatorProductSub           string   `json:"navigator.productSub,omitempty"`
	NavigatorMaxTouchPoints       *uint32  `json:"navigator.maxTouchPoints,omitempty"`
	NavigatorCookieEnabled        *bool    `json:"navigator.cookieEnabled,omitempty"`
	NavigatorGlobalPrivacyControl *bool    `json:"navigator.globalPrivacyControl,omitempty"`
	NavigatorBuildID              string   `json:"navigator.buildID,omitempty"`
	NavigatorOnLine               *bool    `json:"navigator.onLine,omitempty"`

	// screen.*
	ScreenAvailHeight *uint32  `json:"screen.availHeight,omitempty"`
	ScreenAvailWidth  *uint32  `json:"screen.availWidth,omitempty"`
	ScreenAvailTop    *uint32  `json:"screen.availTop,omitempty"`
	ScreenAvailLeft   *uint32  `json:"screen.availLeft,omitempty"`
	ScreenHeight      *uint32  `json:"screen.height,omitempty"`
	ScreenWidth       *uint32  `json:"screen.width,omitempty"`
	ScreenColorDepth  *uint32  `json:"screen.colorDepth,omitempty"`
	ScreenPixelDepth  *uint32  `json:"screen.pixelDepth,omitempty"`
	ScreenPageXOffset *float64 `json:"screen.pageXOffset,omitempty"`
	ScreenPageYOffset *float64 `json:"screen.pageYOffset,omitempty"`
	// screen.orientation (#20) — type + angle, kept coherent with the spoofed
	// screen dimensions so the real host orientation doesn't leak.
	ScreenOrientation      string  `json:"screen:orientation,omitempty"`
	ScreenOrientationAngle *uint32 `json:"screen:orientationAngle,omitempty"`

	// window.*
	WindowScrollMinX        *int32   `json:"window.scrollMinX,omitempty"`
	WindowScrollMinY        *int32   `json:"window.scrollMinY,omitempty"`
	WindowScrollMaxX        *int32   `json:"window.scrollMaxX,omitempty"`
	WindowScrollMaxY        *int32   `json:"window.scrollMaxY,omitempty"`
	WindowOuterHeight       *uint32  `json:"window.outerHeight,omitempty"`
	WindowOuterWidth        *uint32  `json:"window.outerWidth,omitempty"`
	WindowInnerHeight       *uint32  `json:"window.innerHeight,omitempty"`
	WindowInnerWidth        *uint32  `json:"window.innerWidth,omitempty"`
	WindowScreenX           *int32   `json:"window.screenX,omitempty"`
	WindowScreenY           *int32   `json:"window.screenY,omitempty"`
	WindowHistoryLength     *uint32  `json:"window.history.length,omitempty"`
	WindowDevicePixelRatio  *float64 `json:"window.devicePixelRatio,omitempty"`

	// document.body.*
	DocumentBodyClientWidth  *uint32 `json:"document.body.clientWidth,omitempty"`
	DocumentBodyClientHeight *uint32 `json:"document.body.clientHeight,omitempty"`
	DocumentBodyClientTop    *uint32 `json:"document.body.clientTop,omitempty"`
	DocumentBodyClientLeft   *uint32 `json:"document.body.clientLeft,omitempty"`

	// headers.*
	HeadersUserAgent      string `json:"headers.User-Agent,omitempty"`
	HeadersAcceptLanguage string `json:"headers.Accept-Language,omitempty"`
	HeadersAcceptEncoding string `json:"headers.Accept-Encoding,omitempty"`

	// webrtc:*
	WebRTCIPv4      string `json:"webrtc:ipv4,omitempty"`
	WebRTCIPv6      string `json:"webrtc:ipv6,omitempty"`
	WebRTCLocalIPv4 string `json:"webrtc:localipv4,omitempty"`
	WebRTCLocalIPv6 string `json:"webrtc:localipv6,omitempty"`

	PDFViewerEnabled *bool `json:"pdfViewerEnabled,omitempty"`

	// battery:*
	BatteryCharging        *bool    `json:"battery:charging,omitempty"`
	BatteryChargingTime    *float64 `json:"battery:chargingTime,omitempty"`
	BatteryDischargingTime *float64 `json:"battery:dischargingTime,omitempty"`
	BatteryLevel           *float64 `json:"battery:level,omitempty"`

	// fonts / voices
	Fonts            []string `json:"fonts,omitempty"`
	FontsSpacingSeed *uint32  `json:"fonts:spacing_seed,omitempty"`
	AudioSeed        *uint32  `json:"audio:seed,omitempty"`
	CanvasSeed       *uint32  `json:"canvas:seed,omitempty"`

	// geolocation / locale
	GeolocationLatitude  *float64 `json:"geolocation:latitude,omitempty"`
	GeolocationLongitude *float64 `json:"geolocation:longitude,omitempty"`
	GeolocationAccuracy  *float64 `json:"geolocation:accuracy,omitempty"`
	Timezone             string   `json:"timezone,omitempty"`
	LocaleLanguage       string   `json:"locale:language,omitempty"`
	LocaleRegion         string   `json:"locale:region,omitempty"`
	LocaleScript         string   `json:"locale:script,omitempty"`
	LocaleAll            string   `json:"locale:all,omitempty"`

	// humanize / cursor
	Humanize        *bool    `json:"humanize,omitempty"`
	HumanizeMaxTime *float64 `json:"humanize:maxTime,omitempty"`
	HumanizeMinTime *float64 `json:"humanize:minTime,omitempty"`
	ShowCursor      *bool    `json:"showcursor,omitempty"`

	// AudioContext:*
	AudioContextSampleRate      *uint32  `json:"AudioContext:sampleRate,omitempty"`
	AudioContextOutputLatency   *float64 `json:"AudioContext:outputLatency,omitempty"`
	AudioContextMaxChannelCount *uint32  `json:"AudioContext:maxChannelCount,omitempty"`

	// webGl:* / webGl2:*
	WebGLRenderer                            string                 `json:"webGl:renderer,omitempty"`
	WebGLVendor                              string                 `json:"webGl:vendor,omitempty"`
	WebGLSupportedExtensions                 []string               `json:"webGl:supportedExtensions,omitempty"`
	WebGL2SupportedExtensions                []string               `json:"webGl2:supportedExtensions,omitempty"`
	WebGLParameters                          map[string]any         `json:"webGl:parameters,omitempty"`
	WebGLParametersBlockIfNotDefined         *bool                  `json:"webGl:parameters:blockIfNotDefined,omitempty"`
	WebGL2Parameters                         map[string]any         `json:"webGl2:parameters,omitempty"`
	WebGL2ParametersBlockIfNotDefined        *bool                  `json:"webGl2:parameters:blockIfNotDefined,omitempty"`
	WebGLShaderPrecisionFormats              map[string]any         `json:"webGl:shaderPrecisionFormats,omitempty"`
	WebGLShaderPrecisionFormatsBlockIfNotDef *bool                  `json:"webGl:shaderPrecisionFormats:blockIfNotDefined,omitempty"`
	WebGL2ShaderPrecisionFormats             map[string]any         `json:"webGl2:shaderPrecisionFormats,omitempty"`
	WebGL2ShaderPrecisionFormatsBlockIfNoDef *bool                  `json:"webGl2:shaderPrecisionFormats:blockIfNotDefined,omitempty"`
	WebGLContextAttributes                   map[string]any         `json:"webGl:contextAttributes,omitempty"`
	WebGL2ContextAttributes                  map[string]any         `json:"webGl2:contextAttributes,omitempty"`

	// canvas:*
	CanvasAAOffset      *int32   `json:"canvas:aaOffset,omitempty"`
	CanvasAACapOffset   *bool    `json:"canvas:aaCapOffset,omitempty"`
	CanvasNoiseDensity  *float64 `json:"canvas:noiseDensity,omitempty"`
	CanvasNoiseStrength *uint32  `json:"canvas:noiseStrength,omitempty"`

	// voices:*
	Voices                              []Voice  `json:"voices,omitempty"`
	VoicesBlockIfNotDefined             *bool    `json:"voices:blockIfNotDefined,omitempty"`
	VoicesFakeCompletion                *bool    `json:"voices:fakeCompletion,omitempty"`
	VoicesFakeCompletionCharsPerSecond  *float64 `json:"voices:fakeCompletion:charsPerSecond,omitempty"`

	// mediaDevices:*
	MediaDevicesMicros   *uint32 `json:"mediaDevices:micros,omitempty"`
	MediaDevicesWebcams  *uint32 `json:"mediaDevices:webcams,omitempty"`
	MediaDevicesSpeakers *uint32 `json:"mediaDevices:speakers,omitempty"`
	MediaDevicesEnabled  *bool   `json:"mediaDevices:enabled,omitempty"`

	// mediaCapabilities:* — per-OS codec matrix so canPlayType /
	// MediaSource.isTypeSupported / mediaCapabilities.decodingInfo don't leak
	// the host's real decoder support. Keys are codec substrings (e.g. "hvc1").
	MediaCanPlayType  map[string]string          `json:"mediaCapabilities:canPlayType,omitempty"`
	MediaDecodingInfo map[string]MediaDecodeInfo `json:"mediaCapabilities:decodingInfo,omitempty"`

	// cssMedia:* — per-profile CSS media-feature values so a wide-gamut/HDR
	// monitor or the host OS theme doesn't leak through matchMedia.
	// (prefers-reduced-motion is already owned by the Playwright patch.)
	CSSColorGamut         string `json:"cssMedia:colorGamut,omitempty"`
	CSSDynamicRange       string `json:"cssMedia:dynamicRange,omitempty"`
	CSSPrefersColorScheme string `json:"cssMedia:prefersColorScheme,omitempty"`

	// runtime tweaks
	AllowMainWorld   *bool    `json:"allowMainWorld,omitempty"`
	ForceScopeAccess *bool    `json:"forceScopeAccess,omitempty"`
	DisableTheming   *bool    `json:"disableTheming,omitempty"`
	MemorySaver      *bool    `json:"memorysaver,omitempty"`
	Addons           []string `json:"addons,omitempty"`
	CertificatePaths []string `json:"certificatePaths,omitempty"`
	Certificates     []string `json:"certificates,omitempty"`
	Debug            *bool    `json:"debug,omitempty"`

	// Extra allows callers to inject keys not yet captured by named fields
	// (forward-compat with new CAMOU_CONFIG properties).
	Extra map[string]any `json:"-"`
}

// Helpers — make pointer construction less painful at call sites.
func Bool(v bool) *bool          { return &v }
func Uint32(v uint32) *uint32    { return &v }
func Int32(v int32) *int32       { return &v }
func Float64(v float64) *float64 { return &v }
func String(v string) *string    { return &v }
