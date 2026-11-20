' The single Prefixed URL helper: every URL the Lab App requests goes through it.
' Format (ADR-0001): <proxy-base><separator><origin-url>, separator "/" (the lab's own
' form) or "/;" (Charles-style).
' A CA Routing build (Certificates.brs) leaves the Origin URL as it is.
function PrefixedUrl(proxyBase as String, separator as String, originUrl as String) as String
  if CaRouting() then return originUrl
  if Right(proxyBase, 1) = "/" then proxyBase = Left(proxyBase, Len(proxyBase) - 1)
  return proxyBase + separator + originUrl
end function

' True if url is a Prefixed URL with this Proxy Base and separator. Never in a CA Routing
' build: it has no Proxy Base.
function IsPrefixed(proxyBase as String, separator as String, url as String) as Boolean
  labBase = PrefixedUrl(proxyBase, separator, "")
  return labBase <> "" and Left(url, Len(labBase)) = labBase
end function
