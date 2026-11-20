' The kit's wiring, step 1 of 3: keep the proxyBase launch param before the scene starts.
sub Main(args as Dynamic)
  screen = CreateObject("roSGScreen")
  port = CreateObject("roMessagePort")
  screen.setMessagePort(port)
  RoxyStart(screen, args)
  screen.CreateScene("ExampleScene")
  screen.show()

  while true
    msg = wait(0, port)
    if type(msg) = "roSGScreenEvent" and msg.isScreenClosed() then return
  end while
end sub
