sub init()
  m.top.functionName = "fetch"
end sub

sub fetch()
  port = CreateObject("roMessagePort")
  xfer = CreateObject("roUrlTransfer")
  xfer.SetMessagePort(port)
  xfer.SetUrl(m.top.url)
  xfer.SetCertificatesFile(LabCertificatesFile())
  xfer.InitClientCertificates()
  xfer.EnableEncodings(true)
  xfer.RetainBodyOnError(true)
  if m.top.body = ""
    started = xfer.AsyncGetToString()
  else
    xfer.AddHeader("Content-Type", "application/json")
    started = xfer.AsyncPostFromString(m.top.body)
  end if
  if not started
    m.top.result = {status: -999, bytes: 0, fp: "none", text: ""}
    return
  end if

  msg = wait(30000, port)
  if type(msg) <> "roUrlEvent"
    xfer.AsyncCancel()
    m.top.result = {status: -28, bytes: 0, fp: "none", text: ""}
    return
  end if
  text = msg.GetString()
  body = CreateObject("roByteArray")
  body.FromAsciiString(text)
  m.top.result = {status: msg.GetResponseCode(), bytes: body.Count(), fp: Fingerprint(text), text: text}
end sub
