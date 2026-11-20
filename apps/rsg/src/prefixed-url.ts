import { labCertificatesFile } from "./ca-routing";

// The single Prefixed URL helper: every URL the Lab App requests goes through it.
// Format (ADR-0001): <proxy-base>/<origin-url>
// A CA Routing build leaves the Origin URL as it is.
export const prefixedUrl = (proxyBase: string, originUrl: string): string =>
    labCertificatesFile ? originUrl : `${proxyBase.replace(/\/$/, "")}/${originUrl}`;

// True if url is a Prefixed URL with this Proxy Base. Never in a CA Routing build: it has no Proxy Base.
export const isPrefixed = (proxyBase: string, url: string): boolean => {
    const labBase = prefixedUrl(proxyBase, "");
    return labBase !== "" && url.startsWith(labBase);
};
