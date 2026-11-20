' The cases (traffic classes), in menu order. To add one: an entry here plus its sub.
function LabCases() as Object
  return [
    {id: "json_get", label: "JSON GET", run: CaseJsonGet}
    {id: "redirect", label: "Redirect", run: CaseRedirect}
    {id: "hls", label: "HLS", run: CaseHls}
    {id: "dash", label: "DASH", run: CaseDash}
    {id: "widevine", label: "Widevine DASH", run: CaseWidevine}
    {id: "json_post", label: "JSON POST", run: CaseJsonPost}
    {id: "image", label: "Image (from catalog JSON)", run: CaseImage}
    {id: "raf", label: "RAF ad", run: CaseRaf}
    {id: "uuid", label: "JSON GET (changes every time)", run: CaseUuid}
  ]
end function

sub CaseJsonGet()
  HttpGet("https://httpbin.org/json")
end sub

' A new uuid on every request: replay must still give the recorded fp.
sub CaseUuid()
  HttpGet("https://httpbin.org/uuid")
end sub

' A 302 with a relative Location (/json): the lab must keep the second hop in the lab.
' Final hop is the same document as json_get, so its fp matches json_get's.
sub CaseRedirect()
  HttpGet("https://httpbin.org/redirect-to?url=%2Fjson")
end sub

' Absolute variant and segment URIs: they reach the lab only if the body rewriter works.
sub CaseHls()
  PlayVideo("https://stream.mux.com/DS00Spx1CV902MCtPj5WknGlR102V5HFkDe.m3u8", "hls")
end sub

' Relative SegmentTemplate URLs (no public clear DASH uses absolute ones);
' the dash-absolute scenario serves this manifest with an absolute BaseURL.
sub CaseDash()
  PlayVideo("https://dash.akamaized.net/akamai/bbb_30fps/bbb_30fps.mpd", "dash")
end sub

' Widevine DASH (Google test content) with Google's UAT license proxy, both through the lab.
sub CaseWidevine()
  PlayVideo("https://storage.googleapis.com/wvmedia/cenc/h264/tears/tears_sd.mpd", "dash", "https://proxy.uat.widevine.com/proxy?provider=widevine_test")
end sub

' httpbin echoes the body back as the string "data": fp is the echo's, sentfp what was sent.
sub CaseJsonPost()
  m.postBody = "{""case"":""json_post"",""n"":1,""ok"":true}"
  HttpRequest("https://httpbin.org/post", m.postBody, "onJsonPostResult")
end sub

sub onJsonPostResult(event as Object)
  r = event.getData()
  echo = ParseJson(r.text)
  echoed = ""
  if echo <> invalid and GetInterface(echo.data, "ifString") <> invalid then echoed = echo.data
  ReportResult(m.activeCase, [["status", r.status.ToStr()], ["bytes", r.bytes.ToStr()], ["fp", Fingerprint(echoed)], ["sentfp", Fingerprint(m.postBody)]])
end sub

' The Poster's image URL comes only from the catalog JSON, never through PrefixedUrl:
' the image reaches the lab only if the JSON body rewriter made it a Prefixed URL.
sub CaseImage()
  HttpRequest("https://dummyjson.com/products?limit=1&select=title,thumbnail", "", "onCatalogResult")
end sub

sub onCatalogResult(event as Object)
  r = event.getData()
  m.catalogStatus = r.status.ToStr()
  catalog = ParseJson(r.text)
  if catalog = invalid or type(catalog.products) <> "roArray" or catalog.products.Count() = 0
    ReportResult(m.activeCase, [["status", m.catalogStatus], ["poster", "no_catalog"]])
    return
  end if
  uri = catalog.products[0].thumbnail
  m.imagePrefixed = "no"
  if IsPrefixed(m.top.proxyBase, uri) then m.imagePrefixed = "yes"

  if m.poster <> invalid then m.top.removeChild(m.poster)
  m.poster = m.top.createChild("Poster")
  m.poster.translation = [700, 170]
  m.poster.width = 281
  m.poster.height = 281
  m.poster.observeField("loadStatus", "onPosterStatus")
  m.poster.uri = uri
end sub

sub onPosterStatus(event as Object)
  status = event.getData()
  if status = "ready" or status = "failed"
    ReportResult(m.activeCase, [["status", m.catalogStatus], ["prefixed", m.imagePrefixed], ["poster", status]])
  end if
end sub

' A VAST wrapper whose VASTAdTagURI leads to an inline ad: the ad tag, the wrapped tag,
' the media and the beacons reach the lab only if the body rewriter turns them into Prefixed URLs.
sub CaseRaf()
  PlayAd("https://pubads.g.doubleclick.net/gampad/ads?iu=/21775744923/external/single_ad_samples&sz=640x480&cust_params=sample_ct%3Dredirectlinear&ciu_szs=300x250%2C728x90&gdfp_req=1&output=vast&unviewed_position_start=1&env=vp&impl=s&correlator=")
end sub

' --- HTTP cases: one request through HttpTask, reported as status/bytes/fp ---

sub HttpGet(originUrl as String)
  HttpRequest(originUrl, "", "onHttpResult")
end sub

' body "" is a GET, otherwise a JSON POST. onResult names the sub that gets the result.
sub HttpRequest(originUrl as String, body as String, onResult as String)
  m.httpTask = CreateObject("roSGNode", "HttpTask")
  m.httpTask.url = PrefixedUrl(m.top.proxyBase, originUrl)
  m.httpTask.body = body
  m.httpTask.observeField("result", onResult)
  m.httpTask.control = "RUN"
end sub

sub onHttpResult(event as Object)
  r = event.getData()
  ReportResult(m.activeCase, [["status", r.status.ToStr()], ["bytes", r.bytes.ToStr()], ["fp", r.fp]])
end sub

' --- Playback cases: a Video node plays a Prefixed URL, reported as state/errorCode ---
' With a Widevine license server, its URL is Prefixed too and the result adds
' license=<license outcome> (see LicenseOutcome).

sub PlayVideo(originUrl as String, streamFormat as String, licenseUrl = "" as String)
  if m.video <> invalid then m.top.removeChild(m.video)
  content = CreateObject("roSGNode", "ContentNode")
  content.url = PrefixedUrl(m.top.proxyBase, originUrl)
  content.streamFormat = streamFormat
  certificates = LabCertificatesFile() ' Video nodes do not use the scene's HTTP agent
  content.update({HttpCertificatesFile: certificates, DrmHttpCertificatesFile: certificates}, true)
  m.drm = licenseUrl <> ""
  if m.drm then content.drmParams = {keySystem: "widevine", licenseServerURL: PrefixedUrl(m.top.proxyBase, licenseUrl)}
  m.video = m.top.createChild("Video")
  m.video.translation = [700, 170]
  m.video.width = 500
  m.video.height = 281
  m.video.content = content
  m.video.observeField("state", "onVideoState")
  m.video.observeField("streamingSegment", "onStreamingSegment")
  m.video.control = "play"

  m.playbackReported = false
  m.segmentBitrate = invalid
  if m.videoTimeout = invalid ' a stall still yields a result line
    m.videoTimeout = m.top.createChild("Timer")
    m.videoTimeout.duration = 30
    m.videoTimeout.observeField("fire", "onVideoTimeout")
  end if
  m.videoTimeout.control = "start"
end sub

' "playing" is reported once the first video segment streams too (it comes just after),
' so the line carries the bitrate of the variant playback started on.
sub onVideoState(event as Object)
  state = event.getData()
  if state = "error" or state = "finished" or (state = "playing" and m.segmentBitrate <> invalid) then ReportPlayback(state)
end sub

sub onStreamingSegment(event as Object)
  segment = event.getData()
  if segment.segTypeStr <> "mux" and segment.segTypeStr <> "video" then return ' DASH audio comes apart
  if m.segmentBitrate = invalid then m.segmentBitrate = segment.segBitrateBps
  if m.video.state = "playing" then ReportPlayback("playing")
end sub

sub onVideoTimeout()
  ReportPlayback("timeout_" + m.video.state)
end sub

sub ReportPlayback(state as String)
  if m.playbackReported then return ' one result line per run
  m.playbackReported = true
  m.videoTimeout.control = "stop"
  fields = [["state", state], ["errorCode", m.video.errorCode.ToStr()], ["bitrate", SegmentBitrate()]]
  if m.drm then fields.push(["license", LicenseOutcome(m.video.licenseStatus)])
  if state = "error" then print "LABERROR " + m.activeCase + " run=" + m.top.runId + " " + m.video.errorStr
  ReportResult(m.activeCase, fields)
end sub

' The first video segment's bitrate (0 if none yet), so a manifest edit shows in the result line.
' (streamInfo.streamBitrate gave the audio's 128000 on the Roku 3, and is set before any segment.)
function SegmentBitrate() as String
  if m.segmentBitrate = invalid then return "0"
  return m.segmentBitrate.ToStr()
end function

' The license step's outcome: licenseStatus.status as reported, or none if no license was requested.
' Roku OS 16 (Roku 3) reports 2 once the license is acquired and the HTTP status (e.g. 403) when
' the license server fails; the docs promise the HTTP status in both cases.
function LicenseOutcome(licenseStatus as Object) as String
  if licenseStatus = invalid or licenseStatus.status = invalid then return "none"
  return licenseStatus.status.ToStr()
end function

' --- Ad cases: one RAF ad break on a Prefixed ad tag URL ---
' Result: outcome=<completed|no_ads|exited> ads= impressions= completes= errors=
' media=<lab|direct|none> (is the first creative a Prefixed URL?)

sub PlayAd(adTagUrl as String)
  m.adTask = CreateObject("roSGNode", "AdTask")
  m.adTask.adUrl = PrefixedUrl(m.top.proxyBase, adTagUrl)
  m.adTask.view = m.top
  m.adTask.observeField("result", "onAdResult")
  m.adTask.control = "RUN"
end sub

sub onAdResult(event as Object)
  r = event.getData()
  m.menu.setFocus(true) ' RAF takes focus for the break and never gives it back
  media = "none"
  if r.media <> ""
    media = "direct"
    if IsPrefixed(m.top.proxyBase, r.media) then media = "lab"
  end if
  ReportResult(m.activeCase, [["outcome", r.outcome], ["ads", r.ads.ToStr()], ["impressions", r.impressions.ToStr()], ["completes", r.completes.ToStr()], ["errors", r.errors.ToStr()], ["media", media]])
end sub
