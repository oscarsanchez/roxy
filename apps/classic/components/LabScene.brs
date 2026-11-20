' Menu of cases (one per traffic class) plus the result line reporter.
sub init()
  ' The app's default HTTP agent: every node but Video/Audio (Poster...) uses it.
  agent = m.top.getHttpAgent()
  agent.SetCertificatesFile(LabCertificatesFile())
  agent.InitClientCertificates()
  m.cases = LabCases()
  m.menu = m.top.findNode("menu")
  content = CreateObject("roSGNode", "ContentNode")
  for each labCase in m.cases
    content.createChild("ContentNode").title = labCase.label
  end for
  m.menu.content = content
  m.menu.observeField("itemSelected", "onMenuSelected")
  m.menu.setFocus(true)
end sub

sub onProxyBase()
  label = "Proxy Base: " + m.top.proxyBase + ", separator " + m.top.separator
  if CaRouting() then label = "CA Routing build: Origin URLs, no Proxy Base"
  m.top.findNode("proxyBaseLabel").text = label
end sub

sub onCase()
  if m.top.case <> "" then RunCase(m.top.case)
end sub

sub onMenuSelected()
  RunCase(m.cases[m.menu.itemSelected].id)
end sub

sub RunCase(id as String)
  for each labCase in m.cases
    if labCase.id = id
      m.activeCase = id
      caseSub = labCase.run ' "run" itself is a builtin name
      caseSub()
      return
    end if
  end for
  ReportResult(id, [["status", "unknown_case"]])
end sub

' The result line, the grid runner's oracle:
'   LABRESULT <case> run=<run id> <key>=<value>...
sub ReportResult(caseId as String, fields as Object)
  line = "LABRESULT " + caseId + " run=" + m.top.runId
  for each field in fields
    line = line + " " + field[0] + "=" + field[1]
  end for
  print line
  m.top.findNode("resultLabel").text = line
end sub
