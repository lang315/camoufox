package juggler

import "encoding/json"

// TargetInfo is emitted by Browser.attachedToTarget and friends.
// See additions/juggler/protocol/Protocol.js (browserTypes.TargetInfo).
type TargetInfo struct {
	Type             string `json:"type"`
	TargetID         string `json:"targetId"`
	BrowserContextID string `json:"browserContextId,omitempty"`
	OpenerID         string `json:"openerId,omitempty"`
}

// AttachedToTargetEvent — Browser.attachedToTarget params.
type AttachedToTargetEvent struct {
	SessionID  string     `json:"sessionId"`
	TargetInfo TargetInfo `json:"targetInfo"`
}

// DetachedFromTargetEvent — Browser.detachedFromTarget params.
type DetachedFromTargetEvent struct {
	SessionID string `json:"sessionId"`
	TargetID  string `json:"targetId"`
}

// UserPreference — Browser.enable userPrefs entries.
type UserPreference struct {
	Name  string `json:"name"`
	Value any    `json:"value"`
}

// BrowserEnableParams — Browser.enable.
type BrowserEnableParams struct {
	AttachToDefaultContext bool             `json:"attachToDefaultContext"`
	UserPrefs              []UserPreference `json:"userPrefs,omitempty"`
}

// BrowserNewPageParams — Browser.newPage.
type BrowserNewPageParams struct {
	BrowserContextID string `json:"browserContextId,omitempty"`
}

// BrowserNewPageResult — Browser.newPage return.
type BrowserNewPageResult struct {
	TargetID string `json:"targetId"`
}

// CreateBrowserContextParams — Browser.createBrowserContext.
type CreateBrowserContextParams struct {
	RemoveOnDetach bool `json:"removeOnDetach,omitempty"`
}

// CreateBrowserContextResult — Browser.createBrowserContext return.
type CreateBrowserContextResult struct {
	BrowserContextID string `json:"browserContextId"`
}

// RemoveBrowserContextParams — Browser.removeBrowserContext.
type RemoveBrowserContextParams struct {
	BrowserContextID string `json:"browserContextId"`
}

// BrowserGetInfoResult — Browser.getInfo return.
type BrowserGetInfoResult struct {
	UserAgent string `json:"userAgent"`
	Version   string `json:"version"`
}

// HTTPHeader — networkTypes.HTTPHeader.
type HTTPHeader struct {
	Name  string `json:"name"`
	Value string `json:"value"`
}

// Geolocation — browserTypes.Geolocation.
type Geolocation struct {
	Latitude  float64  `json:"latitude"`
	Longitude float64  `json:"longitude"`
	Accuracy  *float64 `json:"accuracy,omitempty"`
}

// PageNavigateParams — Page.navigate.
type PageNavigateParams struct {
	FrameID string `json:"frameId"`
	URL     string `json:"url"`
	Referer string `json:"referer,omitempty"`
}

// PageNavigateResult — Page.navigate return.
type PageNavigateResult struct {
	NavigationID *string `json:"navigationId"`
}

// NavigationCommittedEvent — Page.navigationCommitted.
type NavigationCommittedEvent struct {
	FrameID      string  `json:"frameId"`
	NavigationID *string `json:"navigationId,omitempty"`
	URL          string  `json:"url"`
	Name         string  `json:"name"`
}

// EventFiredEvent — Page.eventFired ('load' / 'DOMContentLoaded').
type EventFiredEvent struct {
	FrameID string `json:"frameId"`
	Name    string `json:"name"`
}

// FrameAttachedEvent — Page.frameAttached.
type FrameAttachedEvent struct {
	FrameID       string `json:"frameId"`
	ParentFrameID string `json:"parentFrameId,omitempty"`
}

// AuxData — runtimeTypes.AuxData.
type AuxData struct {
	FrameID string `json:"frameId,omitempty"`
	Name    string `json:"name,omitempty"`
}

// ExecutionContextCreatedEvent — Runtime.executionContextCreated.
type ExecutionContextCreatedEvent struct {
	ExecutionContextID string  `json:"executionContextId"`
	AuxData            AuxData `json:"auxData"`
}

// RemoteObject — runtimeTypes.RemoteObject.
type RemoteObject struct {
	Type                string          `json:"type,omitempty"`
	Subtype             string          `json:"subtype,omitempty"`
	ObjectID            string          `json:"objectId,omitempty"`
	UnserializableValue string          `json:"unserializableValue,omitempty"`
	Value               json.RawMessage `json:"value,omitempty"`
}

// ExceptionDetails — runtimeTypes.ExceptionDetails.
type ExceptionDetails struct {
	Text  string          `json:"text,omitempty"`
	Stack string          `json:"stack,omitempty"`
	Value json.RawMessage `json:"value,omitempty"`
}

// EvaluateParams — Runtime.evaluate.
type EvaluateParams struct {
	ExecutionContextID string `json:"executionContextId"`
	Expression         string `json:"expression"`
	ReturnByValue      bool   `json:"returnByValue,omitempty"`
}

// EvaluateResult — Runtime.evaluate / Runtime.callFunction return.
type EvaluateResult struct {
	Result           *RemoteObject     `json:"result,omitempty"`
	ExceptionDetails *ExceptionDetails `json:"exceptionDetails,omitempty"`
}

// CallFunctionArgument — runtimeTypes.CallFunctionArgument.
type CallFunctionArgument struct {
	ObjectID            string          `json:"objectId,omitempty"`
	UnserializableValue string          `json:"unserializableValue,omitempty"`
	Value               json.RawMessage `json:"value,omitempty"`
}

// CallFunctionParams — Runtime.callFunction.
type CallFunctionParams struct {
	ExecutionContextID  string                 `json:"executionContextId"`
	FunctionDeclaration string                 `json:"functionDeclaration"`
	ReturnByValue       bool                   `json:"returnByValue,omitempty"`
	Args                []CallFunctionArgument `json:"args"`
}

// PageScreenshotClip — pageTypes.Clip.
type PageScreenshotClip struct {
	X      float64 `json:"x"`
	Y      float64 `json:"y"`
	Width  float64 `json:"width"`
	Height float64 `json:"height"`
}

// PageScreenshotParams — Page.screenshot.
type PageScreenshotParams struct {
	MimeType                string             `json:"mimeType"`
	Clip                    PageScreenshotClip `json:"clip"`
	Quality                 *float64           `json:"quality,omitempty"`
	OmitDeviceScaleFactor   bool               `json:"omitDeviceScaleFactor,omitempty"`
}

// PageScreenshotResult — Page.screenshot return (base64).
type PageScreenshotResult struct {
	Data string `json:"data"`
}

// PageDispatchMouseEventParams — Page.dispatchMouseEvent.
type PageDispatchMouseEventParams struct {
	Type       string  `json:"type"` // mousedown | mousemove | mouseup
	Button     int     `json:"button"`
	X          float64 `json:"x"`
	Y          float64 `json:"y"`
	Modifiers  int     `json:"modifiers"`
	ClickCount *int    `json:"clickCount,omitempty"`
	Buttons    int     `json:"buttons"`
}

// PageDispatchKeyEventParams — Page.dispatchKeyEvent.
type PageDispatchKeyEventParams struct {
	Type     string `json:"type"` // keydown | keyup
	Key      string `json:"key"`
	KeyCode  int    `json:"keyCode"`
	Location int    `json:"location"`
	Code     string `json:"code"`
	Repeat   bool   `json:"repeat"`
	Text     string `json:"text,omitempty"`
}

// InitScript — pageTypes.InitScript.
type InitScript struct {
	Script    string `json:"script"`
	WorldName string `json:"worldName,omitempty"`
}

// PageSetInitScriptsParams — Page.setInitScripts.
type PageSetInitScriptsParams struct {
	Scripts []InitScript `json:"scripts"`
}

// BrowserSetInitScriptsParams — Browser.setInitScripts.
type BrowserSetInitScriptsParams struct {
	BrowserContextID string       `json:"browserContextId,omitempty"`
	Scripts          []InitScript `json:"scripts"`
}

// SetViewportSizeParams — Page.setViewportSize.
type SetViewportSizeParams struct {
	ViewportSize *Size `json:"viewportSize"`
}

// Size — pageTypes.Size.
type Size struct {
	Width  int `json:"width"`
	Height int `json:"height"`
}

// NetworkRequestWillBeSentEvent — Network.requestWillBeSent (partial).
type NetworkRequestWillBeSentEvent struct {
	FrameID        string       `json:"frameId,omitempty"`
	RequestID      string       `json:"requestId"`
	RedirectedFrom string       `json:"redirectedFrom,omitempty"`
	PostData       string       `json:"postData,omitempty"`
	Headers        []HTTPHeader `json:"headers"`
	IsIntercepted  bool         `json:"isIntercepted"`
	URL            string       `json:"url"`
	Method         string       `json:"method"`
	NavigationID   string       `json:"navigationId,omitempty"`
	Cause          string       `json:"cause"`
	InternalCause  string       `json:"internalCause"`
}

// NetworkResponseReceivedEvent — Network.responseReceived (partial).
type NetworkResponseReceivedEvent struct {
	RequestID         string       `json:"requestId"`
	FromCache         bool         `json:"fromCache"`
	RemoteIPAddress   string       `json:"remoteIPAddress,omitempty"`
	RemotePort        int          `json:"remotePort,omitempty"`
	Status            int          `json:"status"`
	StatusText        string       `json:"statusText"`
	Headers           []HTTPHeader `json:"headers"`
	FromServiceWorker bool         `json:"fromServiceWorker"`
}

// DialogOpenedEvent — Page.dialogOpened.
type DialogOpenedEvent struct {
	DialogID     string `json:"dialogId"`
	Type         string `json:"type"`
	Message      string `json:"message"`
	DefaultValue string `json:"defaultValue,omitempty"`
}

// HandleDialogParams — Page.handleDialog.
type HandleDialogParams struct {
	DialogID   string `json:"dialogId"`
	Accept     bool   `json:"accept"`
	PromptText string `json:"promptText,omitempty"`
}

// BindingCalledEvent — Page.bindingCalled.
type BindingCalledEvent struct {
	ExecutionContextID string          `json:"executionContextId"`
	Name               string          `json:"name"`
	Payload            json.RawMessage `json:"payload"`
}

// BrowserSetGeolocationOverrideParams — Browser.setGeolocationOverride.
type BrowserSetGeolocationOverrideParams struct {
	BrowserContextID string       `json:"browserContextId,omitempty"`
	Geolocation      *Geolocation `json:"geolocation"`
}

// BrowserSetUserAgentOverrideParams — Browser.setUserAgentOverride.
type BrowserSetUserAgentOverrideParams struct {
	BrowserContextID string  `json:"browserContextId,omitempty"`
	UserAgent        *string `json:"userAgent"`
}

// BrowserSetTimezoneOverrideParams — Browser.setTimezoneOverride.
type BrowserSetTimezoneOverrideParams struct {
	BrowserContextID string  `json:"browserContextId,omitempty"`
	TimezoneID       *string `json:"timezoneId"`
}

// BrowserSetLocaleOverrideParams — Browser.setLocaleOverride.
type BrowserSetLocaleOverrideParams struct {
	BrowserContextID string  `json:"browserContextId,omitempty"`
	Locale           *string `json:"locale"`
}

// BrowserSetExtraHTTPHeadersParams — Browser.setExtraHTTPHeaders.
type BrowserSetExtraHTTPHeadersParams struct {
	BrowserContextID string       `json:"browserContextId,omitempty"`
	Headers          []HTTPHeader `json:"headers"`
}

// Cookie — browserTypes.Cookie (returned by Browser.getCookies).
type Cookie struct {
	Name     string  `json:"name"`
	Domain   string  `json:"domain"`
	Path     string  `json:"path"`
	Value    string  `json:"value"`
	Expires  float64 `json:"expires"`
	Size     int     `json:"size"`
	HTTPOnly bool    `json:"httpOnly"`
	Secure   bool    `json:"secure"`
	Session  bool    `json:"session"`
	SameSite string  `json:"sameSite"`
}

// CookieOptions — browserTypes.CookieOptions (input to setCookies).
type CookieOptions struct {
	Name     string   `json:"name"`
	Value    string   `json:"value"`
	URL      string   `json:"url,omitempty"`
	Domain   string   `json:"domain,omitempty"`
	Path     string   `json:"path,omitempty"`
	Secure   *bool    `json:"secure,omitempty"`
	HTTPOnly *bool    `json:"httpOnly,omitempty"`
	SameSite string   `json:"sameSite,omitempty"`
	Expires  *float64 `json:"expires,omitempty"`
}

// BrowserGetCookiesParams — Browser.getCookies.
type BrowserGetCookiesParams struct {
	BrowserContextID string `json:"browserContextId,omitempty"`
}

// BrowserGetCookiesResult — Browser.getCookies return.
type BrowserGetCookiesResult struct {
	Cookies []Cookie `json:"cookies"`
}

// BrowserSetCookiesParams — Browser.setCookies.
type BrowserSetCookiesParams struct {
	BrowserContextID string          `json:"browserContextId,omitempty"`
	Cookies          []CookieOptions `json:"cookies"`
}

// BrowserClearCookiesParams — Browser.clearCookies.
type BrowserClearCookiesParams struct {
	BrowserContextID string `json:"browserContextId,omitempty"`
}

// PageGoBackParams — Page.goBack.
type PageGoBackParams struct {
	FrameID string `json:"frameId"`
}

// PageGoBackResult — Page.goBack return.
type PageGoBackResult struct {
	Success bool `json:"success"`
}

// PageGoForwardParams — Page.goForward.
type PageGoForwardParams struct {
	FrameID string `json:"frameId"`
}

// PageGoForwardResult — Page.goForward return.
type PageGoForwardResult struct {
	Success bool `json:"success"`
}

// PageScrollIntoViewIfNeededParams — Page.scrollIntoViewIfNeeded.
type PageScrollIntoViewIfNeededParams struct {
	FrameID  string `json:"frameId"`
	ObjectID string `json:"objectId"`
}

// DOMPoint — one vertex in a DOMQuad.
type DOMPoint struct {
	X float64 `json:"x"`
	Y float64 `json:"y"`
	W float64 `json:"w"`
}

// DOMQuad — pageTypes.DOMQuad (four-point polygon).
type DOMQuad struct {
	P1 DOMPoint `json:"p1"`
	P2 DOMPoint `json:"p2"`
	P3 DOMPoint `json:"p3"`
	P4 DOMPoint `json:"p4"`
}

// PageGetContentQuadsParams — Page.getContentQuads.
type PageGetContentQuadsParams struct {
	FrameID  string `json:"frameId"`
	ObjectID string `json:"objectId"`
}

// PageGetContentQuadsResult — Page.getContentQuads return.
type PageGetContentQuadsResult struct {
	Quads []DOMQuad `json:"quads"`
}

// PageDispatchWheelEventParams — Page.dispatchWheelEvent.
type PageDispatchWheelEventParams struct {
	X         float64 `json:"x"`
	Y         float64 `json:"y"`
	DeltaX    float64 `json:"deltaX"`
	DeltaY    float64 `json:"deltaY"`
	DeltaZ    float64 `json:"deltaZ"`
	Modifiers int     `json:"modifiers"`
}

// RuntimeConsoleEvent — Runtime.console.
type RuntimeConsoleEvent struct {
	ExecutionContextID string         `json:"executionContextId"`
	Args               []RemoteObject `json:"args"`
	Type               string         `json:"type"`
}

// PageUncaughtErrorEvent — Page.uncaughtError.
type PageUncaughtErrorEvent struct {
	FrameID string `json:"frameId"`
	Message string `json:"message"`
	Stack   string `json:"stack"`
}

// BrowserGrantPermissionsParams — Browser.grantPermissions.
type BrowserGrantPermissionsParams struct {
	BrowserContextID string   `json:"browserContextId,omitempty"`
	Origin           string   `json:"origin"`
	Permissions      []string `json:"permissions"`
}

// BrowserResetPermissionsParams — Browser.resetPermissions.
type BrowserResetPermissionsParams struct {
	BrowserContextID string `json:"browserContextId,omitempty"`
}

// PageSetFileInputFilesParams — Page.setFileInputFiles.
type PageSetFileInputFilesParams struct {
	FrameID  string   `json:"frameId"`
	ObjectID string   `json:"objectId"`
	Files    []string `json:"files"`
}

// PageSetInterceptFileChooserParams — Page.setInterceptFileChooserDialog.
type PageSetInterceptFileChooserParams struct {
	Enabled bool `json:"enabled"`
}

// FileChooserOpenedEvent — Page.fileChooserOpened.
type FileChooserOpenedEvent struct {
	ExecutionContextID string       `json:"executionContextId"`
	Element            RemoteObject `json:"element"`
}

// DownloadOptionsInner — browserTypes.DownloadOptions (nested).
// Behavior values: "saveToDisk" | "cancel".
type DownloadOptionsInner struct {
	Behavior     string `json:"behavior,omitempty"`
	DownloadsDir string `json:"downloadsDir,omitempty"`
}

// BrowserSetDownloadOptionsParams — Browser.setDownloadOptions.
type BrowserSetDownloadOptionsParams struct {
	BrowserContextID string                `json:"browserContextId,omitempty"`
	DownloadOptions  *DownloadOptionsInner `json:"downloadOptions"`
}

// BrowserCancelDownloadParams — Browser.cancelDownload.
type BrowserCancelDownloadParams struct {
	UUID string `json:"uuid,omitempty"`
}

// DownloadCreatedEvent — Browser.downloadCreated.
type DownloadCreatedEvent struct {
	UUID              string `json:"uuid"`
	BrowserContextID  string `json:"browserContextId,omitempty"`
	PageTargetID      string `json:"pageTargetId"`
	FrameID           string `json:"frameId"`
	URL               string `json:"url"`
	SuggestedFileName string `json:"suggestedFileName"`
}

// DownloadFinishedEvent — Browser.downloadFinished.
type DownloadFinishedEvent struct {
	UUID     string `json:"uuid"`
	Canceled bool   `json:"canceled,omitempty"`
	Error    string `json:"error,omitempty"`
}

// AXNode — axTypes.AXTree; one node in the accessibility tree.
type AXNode struct {
	Role            string    `json:"role"`
	Name            string    `json:"name"`
	Children        []*AXNode `json:"children,omitempty"`
	Selected        bool      `json:"selected,omitempty"`
	Focused         bool      `json:"focused,omitempty"`
	Pressed         bool      `json:"pressed,omitempty"`
	Focusable       bool      `json:"focusable,omitempty"`
	Required        bool      `json:"required,omitempty"`
	Invalid         bool      `json:"invalid,omitempty"`
	Modal           bool      `json:"modal,omitempty"`
	Editable        bool      `json:"editable,omitempty"`
	Busy            bool      `json:"busy,omitempty"`
	Multiline       bool      `json:"multiline,omitempty"`
	Readonly        bool      `json:"readonly,omitempty"`
	Expanded        bool      `json:"expanded,omitempty"`
	Disabled        bool      `json:"disabled,omitempty"`
	Multiselectable bool      `json:"multiselectable,omitempty"`
	Value           string    `json:"value,omitempty"`
	HasPopup        string    `json:"haspopup,omitempty"`
}

// AccessibilityGetFullAXTreeParams — Accessibility.getFullAXTree.
type AccessibilityGetFullAXTreeParams struct {
	ObjectID string `json:"objectId,omitempty"`
}

// AccessibilityGetFullAXTreeResult — Accessibility.getFullAXTree return.
type AccessibilityGetFullAXTreeResult struct {
	Tree *AXNode `json:"tree"`
}

// TouchPoint — pageTypes.TouchPoint.
type TouchPoint struct {
	X             float64  `json:"x"`
	Y             float64  `json:"y"`
	RadiusX       *float64 `json:"radiusX,omitempty"`
	RadiusY       *float64 `json:"radiusY,omitempty"`
	RotationAngle *float64 `json:"rotationAngle,omitempty"`
	Force         *float64 `json:"force,omitempty"`
}

// PageDispatchTouchEventParams — Page.dispatchTouchEvent.
// Type values: "touchStart" | "touchEnd" | "touchMove" | "touchCancel".
type PageDispatchTouchEventParams struct {
	Type        string       `json:"type"`
	TouchPoints []TouchPoint `json:"touchPoints"`
	Modifiers   int          `json:"modifiers"`
}

// PageDispatchTouchEventResult — Page.dispatchTouchEvent return.
type PageDispatchTouchEventResult struct {
	DefaultPrevented bool `json:"defaultPrevented"`
}

// PageDispatchTapEventParams — Page.dispatchTapEvent.
type PageDispatchTapEventParams struct {
	X         float64 `json:"x"`
	Y         float64 `json:"y"`
	Modifiers int     `json:"modifiers"`
}

// BrowserSetTouchOverrideParams — Browser.setTouchOverride.
// HasTouch nil removes the override.
type BrowserSetTouchOverrideParams struct {
	BrowserContextID string `json:"browserContextId,omitempty"`
	HasTouch         *bool  `json:"hasTouch"`
}

// PageAddBindingParams — Page.addBinding (Protocol.js L791).
// Script is evaluated after the binding is installed; it can reference
// window[Name] to set up observers that call back into Go.
type PageAddBindingParams struct {
	WorldName string `json:"worldName,omitempty"`
	Name      string `json:"name"`
	Script    string `json:"script"`
}

// PageBindingCalledEvent — Page.bindingCalled (Protocol.js L714).
type PageBindingCalledEvent struct {
	ExecutionContextID string `json:"executionContextId"`
	Name               string `json:"name"`
	Payload            string `json:"payload"`
}
