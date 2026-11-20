' The fp in result lines: the first 12 hex digits of the text's SHA-1.
function Fingerprint(text as String) as String
  bytes = CreateObject("roByteArray")
  bytes.FromAsciiString(text)
  digest = CreateObject("roEVPDigest")
  digest.Setup("sha1")
  return Left(digest.Process(bytes), 12)
end function
