sub init()
  ' The kit's wiring, step 2 of 3: the scene's HTTP agent (Poster and every node but
  ' Video/Audio) trusts the kit's bundle.
  RoxyTrust(m.top.getHttpAgent())

  ' Step 3: every URL the app requests goes through RoxyUrl.
  url = RoxyUrl("https://httpbin.org/json")
  m.top.findNode("urlLabel").text = "GET " + url
  m.task = CreateObject("roSGNode", "JsonTask")
  m.task.url = url
  m.task.observeField("result", "onResult")
  m.task.control = "run"
end sub

sub onResult()
  line = "status=" + m.task.result.status.ToStr() + " length=" + m.task.result.length.ToStr()
  print "ROXYKIT " + line
  m.top.findNode("resultLabel").text = line
end sub
