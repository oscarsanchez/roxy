// A CA Routing build (scripts/deploy --ca-routing) calls Origin URLs directly, which DNS
// sends to the lab, and trusts this certificate bundle (public roots plus the lab's CA)
// on every request and on the Video. Undefined in a Prefix Routing build.
export const labCertificatesFile: string | undefined = __LAB_CA_BUNDLE__ || undefined;
