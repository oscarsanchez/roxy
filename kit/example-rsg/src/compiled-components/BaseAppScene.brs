' Copyright (c) 2026 Roku, Inc.
' SPDX-License-Identifier: MIT

sub init()
    m.top.backgroundColor = "0x000000FF"
    exampleApp = m.top.findNode("exampleApp")
    if exampleApp <> invalid then exampleApp.setFocus(true)
end sub
