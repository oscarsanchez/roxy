Library "Roku_Ads.brs"

sub init()
  m.top.functionName = "playAds"
end sub

' Request the ad tag, then render whatever ads came back. RAF fetches the ad tag,
' wrappers, media and beacons itself; they reach the lab as Prefixed URLs, or in a
' CA Routing build through DNS.
sub playAds()
  raf = Roku_Ads()
  raf.setDebugOutput(true) ' RAF logs what it fires: compare with mitmweb to find bypasses
  raf.setAdUrl(m.top.adUrl)
  ' A CA Routing build makes RAF trust the lab's CA in two undocumented ways (found on
  ' Roku OS 16.0.4): setCertificatesFile, a member of every RAF instance, covers RAF's
  ' own requests (ad tag, wrappers, beacons); without it the ad tag fails with OpenSSL
  ' error 20. The player's certificates come from each ad (below).
  if CaRouting() then raf.setCertificatesFile(LabCertificatesFile())
  m.tally = {impressions: 0, completes: 0, errors: 0, media: ""}
  raf.setTrackingCallback(onTracking, m.tally)

  pods = raf.getAds()
  ads = 0
  if pods <> invalid
    for each pod in pods
      if pod.ads <> invalid
        ads = ads + pod.ads.Count()
        ' RAF copies an ad's HttpCertificatesFile into its player's content; set on
        ' the ad's streams it is ignored (render failure -3, the creative's TLS refused).
        if CaRouting()
          for each ad in pod.ads
            ad.HttpCertificatesFile = LabCertificatesFile()
          end for
        end if
      end if
    end for
  end if

  outcome = "no_ads"
  if ads > 0
    m.tally.media = FirstStreamUrl(pods)
    outcome = "exited"
    if raf.showAds(pods, invalid, m.top.view) then outcome = "completed"
  end if
  m.tally.outcome = outcome
  m.tally.ads = ads
  m.top.result = m.tally
end sub

sub onTracking(tally = invalid as Dynamic, eventType = invalid as Dynamic, ctx = invalid as Dynamic)
  if eventType = "Impression" then tally.impressions = tally.impressions + 1
  if eventType = "Complete" then tally.completes = tally.completes + 1
  if eventType = "Error" then tally.errors = tally.errors + 1
end sub

' The creative RAF will play first (ctx.url is not set for client-inserted ads on a Roku 3).
function FirstStreamUrl(pods as Object) as String
  for each pod in pods
    if pod.ads <> invalid
      for each ad in pod.ads
        if ad.streams <> invalid and ad.streams.Count() > 0 then return ad.streams[0].url
      end for
    end if
  end for
  return ""
end function
