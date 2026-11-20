import { labCertificatesFile } from "./ca-routing";

// The single Prefixed URL helper: every URL the Lab App requests goes through it.
// Format (ADR-0001): <proxy-base><separator><origin-url>, separator "/" (the lab's own
// form) or "/;" (Charles-style).
// A CA Routing build leaves the Origin URL as it is.
export const prefixedUrl = (proxyBase: string, separator: string, originUrl: string): string =>
    labCertificatesFile ? originUrl : `${proxyBase.replace(/\/$/, "")}${separator}${originUrl}`;

// True if url is a Prefixed URL with this Proxy Base and separator. Never in a CA Routing
// build: it has no Proxy Base.
export const isPrefixed = (proxyBase: string, separator: string, url: string): boolean => {
    const labBase = prefixedUrl(proxyBase, separator, "");
    return labBase !== "" && url.startsWith(labBase);
};
