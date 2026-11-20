' roxy kit for classic BrightScript/SceneGraph apps. Copy this file into source/ and
' include it (<script uri="pkg:/source/RoxyKit.brs"/>) in every component that
' builds a URL or sets up an HTTP agent. Guide: docs/prefix-routing.md, The kit.
'
' Everything that reaches the lab is compiled only when the manifest sets
'   bs_const=roxy_kit=true
' A release build keeps roxy_kit=false: every function below then leaves URLs as they
' are and trusts Roku's certificate bundle only, as an app without the kit does.

' Call in Main before CreateScene: keeps the proxyBase launch param for every thread.
sub RoxyStart(screen as Object, args as Dynamic)
#if roxy_kit
  proxyBase = ""
  if args <> invalid and args.proxyBase <> invalid then proxyBase = args.proxyBase
  if Right(proxyBase, 1) = "/" then proxyBase = Left(proxyBase, Len(proxyBase) - 1)
  screen.getGlobalNode().addFields({roxyProxyBase: proxyBase})
#end if
end sub

' The Charles-style Prefixed URL <proxy-base>/;<url>. The URL is returned as it is
' without a proxyBase launch param, for a non-http(s) URL (pkg:/, tmp:/) and for a URL
' that already carries the Proxy Base (one the lab rewrote in a response).
' Call it from a component or a Task (it reads m.global).
function RoxyUrl(url as String) as String
#if roxy_kit
  proxyBase = ""
  if m.global <> invalid and m.global.roxyProxyBase <> invalid then proxyBase = m.global.roxyProxyBase
  isHttp = LCase(Left(url, 7)) = "http://" or LCase(Left(url, 8)) = "https://"
  isPrefixed = proxyBase <> "" and Left(url, Len(proxyBase) + 1) = proxyBase + "/"
  if isHttp and proxyBase <> "" and not isPrefixed then return proxyBase + "/;" + url
#end if
  return url
end function

' The certificate bundle for every agent: Roku's, plus the lab's CA when the package
' carries it as pkg:/certs/lab-ca.crt (CA Routing). The two are combined on the device,
' so Roku's part stays as current as the device.
function RoxyCertificatesFile() as String
  rokuBundle = "common:/certs/ca-bundle.crt"
#if roxy_kit
  labCa = RoxyLabCa()
  if labCa <> ""
    bundle = "tmp:/lab-ca-bundle.crt"
    if MatchFiles("tmp:/", "lab-ca-bundle.crt").Count() = 0 ' roFileSystem is invalid on the render thread
      WriteAsciiFile(bundle, ReadAsciiFile(rokuBundle) + Chr(10) + labCa)
    end if
    return bundle
  end if
#end if
  return rokuBundle
end function

' The lab's CA if the package carries it (a CA Routing build), else "".
function RoxyLabCa() as String
#if roxy_kit
  return ReadAsciiFile("pkg:/certs/lab-ca.crt")
#end if
  return ""
end function

' roUrlTransfer, or an roHttpAgent: m.top.getHttpAgent() in the scene's init() is the
' agent of Poster and every other node that is not a Video or Audio.
sub RoxyTrust(agent as Object)
  agent.SetCertificatesFile(RoxyCertificatesFile())
  agent.InitClientCertificates()
end sub

' A Video's content node: its media and its DRM license requests.
sub RoxyTrustContent(content as Object)
  certificates = RoxyCertificatesFile()
  content.update({HttpCertificatesFile: certificates, DrmHttpCertificatesFile: certificates}, true)
end sub

' RAF has no documented certificate API. Two undocumented ways work (Roku OS 16.0.4):
' RoxyTrustAds(raf) before getAds() covers RAF's own requests (ad tag, wrappers,
' beacons); RoxyTrustAdPods(pods) after it, before showAds(), covers each ad's player.
' Both do nothing unless the package carries the lab's CA.
sub RoxyTrustAds(raf as Object)
#if roxy_kit
  if RoxyLabCa() <> "" then raf.setCertificatesFile(RoxyCertificatesFile())
#end if
end sub

sub RoxyTrustAdPods(pods as Dynamic)
#if roxy_kit
  if pods = invalid or RoxyLabCa() = "" then return
  for each pod in pods
    if pod.ads <> invalid
      for each ad in pod.ads
        ad.HttpCertificatesFile = RoxyCertificatesFile() ' on the ad's streams it is ignored
      end for
    end if
  end for
#end if
end sub
