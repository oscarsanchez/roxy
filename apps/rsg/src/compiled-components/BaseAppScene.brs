' Copyright (c) 2026 Roku, Inc.
' SPDX-License-Identifier: MIT

sub init()
    m.top.backgroundColor = "0x000000FF"
    labApp = m.top.findNode("labApp")
    if labApp <> invalid then labApp.setFocus(true)
end sub
