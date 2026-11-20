// roxy kit for RSG 2.0 apps. Copy it into src/, with roxy-config.ts next to roku-config.ts.
// Guide: docs/prefix-routing.md, The kit.
//
// Everything that reaches the lab is compiled only when the build sets ROXY_KIT=1
// (roxy-config.ts). Without it these exports leave URLs as they are and add no agent,
// and the bundler drops the rest: a release build carries no proxy code.
import { useLaunchConfig } from "@roku-sdk/runtime/launch-config";
import { type Accessor, untrack } from "@roku-sdk/solid";

// From roxy-config.ts (app.buildVariables).
declare const __ROXY_KIT__: boolean;
declare const __ROXY_CA_BUNDLE__: string;

// The proxyBase launch param, without a trailing slash; "" when the app was launched without
// one. undefined until the launch params arrive: the SDK delivers them after the first render,
// so start requests once it is defined. Call it in the root component.
function useLaunchProxyBase(): Accessor<string | undefined> {
    const { launchParams } = useLaunchConfig<{ proxyBase?: string }>();
    const first = untrack(launchParams);
    return () => {
        const params = launchParams();
        if (params === first && Object.keys(params).length === 0) return undefined;
        return (params.proxyBase ?? "").replace(/\/$/, "");
    };
}

// The Charles-style Prefixed URL <proxy-base>/;<url>. The URL is returned as it is without
// a Proxy Base, for a non-http(s) URL (pkg:/, tmp:/) and for a URL that already carries the
// Proxy Base (one the lab rewrote in a response).
function kitPrefixedUrl(proxyBase: string | undefined, url: string): string {
    if (!proxyBase || !/^https?:\/\//i.test(url) || url.startsWith(`${proxyBase}/`)) return url;
    return `${proxyBase}/;${url}`;
}

export const useProxyBase: () => Accessor<string | undefined> = __ROXY_KIT__ ? useLaunchProxyBase : () => () => "";

export const prefixedUrl: (proxyBase: string | undefined, url: string) => string = __ROXY_KIT__
    ? kitPrefixedUrl
    : (_proxyBase, url) => url;

// The CA Routing bundle (public roots plus the lab's CA), for a Video's content node
// (httpCertificatesFile, which covers its license requests too). undefined without one.
export const roxyCertificatesFile: string | undefined = (__ROXY_KIT__ && __ROXY_CA_BUNDLE__) || undefined;

// A Request's init with an HttpsAgent that trusts roxyCertificatesFile, when there is one.
// Per request: HttpsAgent.setGlobalAgent is undefined at runtime.
export const withRoxyAgent = (init: RequestInit = {}): RequestInit => ({
    ...init,
    ...(roxyCertificatesFile ? { agent: new HttpsAgent({ certificatesFile: roxyCertificatesFile }) } : {})
});
