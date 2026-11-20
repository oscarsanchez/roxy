sub init()
  m.top.functionName = "fetch"
end sub

sub fetch()
  xfer = CreateObject("roUrlTransfer")
  xfer.SetUrl(m.top.url)
  RoxyTrust(xfer) ' every roUrlTransfer trusts the kit's bundle
  xfer.RetainBodyOnError(true)
  port = CreateObject("roMessagePort")
  xfer.SetMessagePort(port)
  if not xfer.AsyncGetToString()
    m.top.result = {status: -999, length: 0}
    return
  end if
  msg = wait(30000, port)
  if type(msg) <> "roUrlEvent"
    xfer.AsyncCancel()
    m.top.result = {status: -28, length: 0}
    return
  end if
  m.top.result = {status: msg.GetResponseCode(), length: Len(msg.GetString())}
end sub
