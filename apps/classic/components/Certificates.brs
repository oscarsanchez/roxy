' The certificate bundle that every HTTP agent of the Lab App uses.
' Prefix Routing: Roku's bundle (an https Proxy Base, the tunnel, needs it).
' CA Routing build (scripts/deploy --ca-routing): Roku's bundle plus the lab's CA
' (pkg:/certs/lab-ca.crt), combined on the device so Roku's part stays current.
function LabCertificatesFile() as String
  rokuBundle = "common:/certs/ca-bundle.crt"
  if not CaRouting() then return rokuBundle
  bundle = "tmp:/lab-ca-bundle.crt"
  if MatchFiles("tmp:/", "lab-ca-bundle.crt").Count() = 0 ' roFileSystem is invalid on the render thread
    WriteAsciiFile(bundle, ReadAsciiFile(rokuBundle) + Chr(10) + ReadAsciiFile("pkg:/certs/lab-ca.crt"))
  end if
  return bundle
end function

' A CA Routing build calls Origin URLs directly; DNS sends them to the lab.
function CaRouting() as Boolean
  return CreateObject("roAppInfo").GetValue("lab_ca_routing") = "true"
end function
