' Launch args (ECP): proxyBase, separator, case, run. Without proxyBase, the build-time
' default from the manifest (lab_proxy_base, stamped by scripts/deploy) is used.
' separator=/; builds Charles-style Prefixed URLs; anything else, the lab's own "/".
sub Main(args as Dynamic)
  screen = CreateObject("roSGScreen")
  port = CreateObject("roMessagePort")
  screen.setMessagePort(port)
  scene = screen.CreateScene("LabScene")

  proxyBase = LaunchArg(args, "proxyBase")
  if proxyBase = "" then proxyBase = CreateObject("roAppInfo").GetValue("lab_proxy_base")
  scene.proxyBase = proxyBase
  if LaunchArg(args, "separator") = "/;" then scene.separator = "/;"
  scene.runId = LaunchArg(args, "run")
  screen.show()
  scene.case = LaunchArg(args, "case") ' set last: runs the case straight away

  while true
    msg = wait(0, port)
    if type(msg) = "roSGScreenEvent" and msg.isScreenClosed() then return
  end while
end sub

function LaunchArg(args as Dynamic, name as String) as String
  if args = invalid or args[name] = invalid then return ""
  return args[name]
end function
