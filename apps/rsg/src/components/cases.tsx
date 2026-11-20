import { type AdPod, Ads, type AdsCommand, type AdsState } from "@roku-sdk/ads";
import { type ILicenseStatus, Video, VideoContentNode, type VideoRef } from "@roku-sdk/components";
import type { DomNode } from "@roku-sdk/interfaces";
import { type Component, createSignal, onCleanup, onMount } from "@roku-sdk/solid";

import { labCertificatesFile } from "../ca-routing";
import { bodyFields, httpRequest, textFingerprint } from "../http";
import { isPrefixed, prefixedUrl } from "../prefixed-url";
import type { Report } from "../result";

export type CaseProps = { proxyBase: string; separator: string; report: Report };

const PLAYBACK_TIMEOUT_MS = 30000;
const AD_TIMEOUT_MS = 50000; // the ad tag, its wrapped tag and a 10 s ad

// An unexpected exception still yields a result line.
function attempt(report: Report, work: () => Promise<void>): void {
    work().catch(e => {
        console.error(`lab case failed: ${String(e)}`);
        report([["status", "app_error"]]);
    });
}

// --- HTTP cases: one request through fetch, reported as status/bytes/fp ---

const HttpGet: Component<CaseProps & { originUrl: string }> = props => {
    onMount(() =>
        attempt(props.report, async () => {
            props.report(await bodyFields(await httpRequest(prefixedUrl(props.proxyBase, props.separator, props.originUrl))));
        })
    );
    return <group />;
};

const JsonGet: Component<CaseProps> = props => <HttpGet {...props} originUrl="https://httpbin.org/json" />;

// A 302 with a relative Location (/json): the lab must keep the second hop in the lab.
// Final hop is the same document as json_get, so its fp matches json_get's.
const Redirect: Component<CaseProps> = props => (
    <HttpGet {...props} originUrl="https://httpbin.org/redirect-to?url=%2Fjson" />
);

// httpbin echoes the body back as the string "data": fp is the echo's, sentfp what was sent.
const JsonPost: Component<CaseProps> = props => {
    const body = JSON.stringify({ case: "json_post", n: 1, ok: true });
    onMount(() =>
        attempt(props.report, async () => {
            const result = await httpRequest(prefixedUrl(props.proxyBase, props.separator, "https://httpbin.org/post"), body);
            const [status, bytes] = await bodyFields(result);
            props.report([
                status,
                bytes,
                ["fp", await textFingerprint(echoedData(result.text))],
                ["sentfp", await textFingerprint(body)]
            ]);
        })
    );
    return <group />;
};

function echoedData(text: string | undefined): string {
    try {
        const echo = JSON.parse(text ?? "") as { data?: unknown };
        return typeof echo.data === "string" ? echo.data : "";
    } catch {
        return "";
    }
}

// The Poster's image URL comes only from the catalog JSON, never through prefixedUrl:
// the image reaches the lab only if the JSON body rewriter made it a Prefixed URL.
const Image: Component<CaseProps> = props => {
    const [uri, setUri] = createSignal<string>();
    let status = "";
    let prefixed = "no";
    onMount(() =>
        attempt(props.report, async () => {
            const catalog = await httpRequest(
                prefixedUrl(props.proxyBase, props.separator, "https://dummyjson.com/products?limit=1&select=title,thumbnail")
            );
            status = catalog.status;
            const thumbnail = catalogThumbnail(catalog.text);
            if (!thumbnail) {
                props.report([["status", status], ["poster", "no_catalog"]]);
                return;
            }
            if (isPrefixed(props.proxyBase, props.separator, thumbnail)) prefixed = "yes";
            setUri(thumbnail);
        })
    );
    // uri last: a handler set after it misses the load status of a cached image.
    return (
        <poster
            translation={[1050, 255]}
            width={420}
            height={420}
            onLoadStatus={loadStatus => {
                if (loadStatus === "ready" || loadStatus === "failed") {
                    props.report([["status", status], ["prefixed", prefixed], ["poster", loadStatus]]);
                }
            }}
            uri={uri()}
        />
    );
};

function catalogThumbnail(text: string | undefined): string | undefined {
    try {
        const catalog = JSON.parse(text ?? "") as { products?: { thumbnail?: unknown }[] };
        const thumbnail = catalog.products?.[0]?.thumbnail;
        return typeof thumbnail === "string" ? thumbnail : undefined;
    } catch {
        return undefined;
    }
}

// --- Playback cases: a Video plays a Prefixed URL, reported as state/errorCode ---
// A stall still yields a line. With a Widevine license server, its URL is Prefixed too
// and the result adds license=<license outcome> (see licenseOutcome).

const PlayVideo: Component<
    CaseProps & { originUrl: string; streamFormat: "hls" | "dash"; licenseUrl?: string }
> = props => {
    let video!: VideoRef;
    let state = "none";
    let errorCode = 0;
    let licenseStatus: ILicenseStatus | undefined;
    let segmentBitrate: number | undefined; // the first video segment's, so a manifest edit shows
    const report = (finalState: string) =>
        props.report([
            ["state", finalState],
            ["errorCode", errorCode],
            ["bitrate", segmentBitrate ?? 0],
            ...(props.licenseUrl ? [["license", licenseOutcome(licenseStatus)] as [string, string]] : [])
        ]);
    // Built once: an inline content={<VideoContentNode/>} is rebuilt on every prop read.
    const content = (
        <VideoContentNode
            url={prefixedUrl(props.proxyBase, props.separator, props.originUrl)}
            streamFormat={props.streamFormat}
            // Sets the Video's HttpAgent, which also fetches the license. SDK 2.19.1 types have
            // no DrmHttpCertificatesFile.
            httpCertificatesFile={labCertificatesFile}
            drmParams={
                props.licenseUrl
                    ? { keySystem: "widevine", licenseServerURL: prefixedUrl(props.proxyBase, props.separator, props.licenseUrl) }
                    : undefined
            }
        />
    );
    const timeout = setTimeout(() => report(`timeout_${state}`), PLAYBACK_TIMEOUT_MS);
    onCleanup(() => clearTimeout(timeout));
    onMount(() => video.play()); // control="play" can race the content
    return (
        <Video
            ref={video}
            translation={[1050, 255]}
            width={750}
            height={422}
            content={content}
            onErrorCode={code => (errorCode = code)}
            onErrorStr={errorStr => console.warn(`playback error: ${errorStr}`)}
            onLicenseStatus={status => (licenseStatus = status)}
            // "playing" is reported once the first video segment streams too (it comes just after),
            // so the line carries the bitrate of the variant playback started on.
            onStreamingSegment={segment => {
                if (segment.segTypeStr !== "mux" && segment.segTypeStr !== "video") return; // DASH audio comes apart
                segmentBitrate ??= segment.segBitrateBps;
                if (state === "playing") report("playing");
            }}
            onState={newState => {
                state = newState;
                if (newState === "playing" && segmentBitrate !== undefined) report(newState);
                // errorCode (and licenseStatus) may arrive just after the state: let them land first.
                // "finished" waits too, so it cannot overtake an "error" just before it.
                if (newState === "error" || newState === "finished") setTimeout(() => report(newState), 0);
            }}
        />
    );
};

// The license step's outcome: licenseStatus.status as reported, or none if no license was requested.
// Roku OS 16 (Roku 3) reports 2 once the license is acquired and the HTTP status (e.g. 403) when
// the license server fails; the docs promise the HTTP status in both cases.
const licenseOutcome = (licenseStatus: ILicenseStatus | undefined): string =>
    licenseStatus?.status === undefined ? "none" : String(licenseStatus.status);

// Absolute variant and segment URIs: they reach the lab only if the body rewriter works.
const Hls: Component<CaseProps> = props => (
    <PlayVideo
        {...props}
        originUrl="https://stream.mux.com/DS00Spx1CV902MCtPj5WknGlR102V5HFkDe.m3u8"
        streamFormat="hls"
    />
);

// Relative SegmentTemplate URLs (no public clear DASH uses absolute ones);
// the dash-absolute scenario serves this manifest with an absolute BaseURL.
const Dash: Component<CaseProps> = props => (
    <PlayVideo {...props} originUrl="https://dash.akamaized.net/akamai/bbb_30fps/bbb_30fps.mpd" streamFormat="dash" />
);

// Widevine DASH (Google test content) with Google's UAT license proxy, both through the lab.
const Widevine: Component<CaseProps> = props => (
    <PlayVideo
        {...props}
        originUrl="https://storage.googleapis.com/wvmedia/cenc/h264/tears/tears_sd.mpd"
        streamFormat="dash"
        licenseUrl="https://proxy.uat.widevine.com/proxy?provider=widevine_test"
    />
);

// --- Ad case: one RAF ad break (CSAI through @roku-sdk/ads) on a Prefixed ad tag URL ---
// A VAST wrapper whose VASTAdTagURI leads to an inline ad: the ad tags, the media and the
// beacons reach the lab only if the body rewriter turns them into Prefixed URLs.
// Result: outcome=<completed|no_ads|exited|error|timeout_<ads state>> ads= impressions=na
// completes=na errors=na media=<lab|direct|none>. The classic fields are kept, but the SDK's
// <Ads> task has no tracking callback, so the beacon counts are "na": count them in mitmweb.

const AD_TAG =
    "https://pubads.g.doubleclick.net/gampad/ads?iu=/21775744923/external/single_ad_samples&sz=640x480&cust_params=sample_ct%3Dredirectlinear&ciu_szs=300x250%2C728x90&gdfp_req=1&output=vast&unviewed_position_start=1&env=vp&impl=s&correlator=";

const Raf: Component<CaseProps> = props => {
    let adView!: DomNode;
    const [command, setCommand] = createSignal<AdsCommand>("none");
    // RAF logs what it fires: compare with mitmweb to find bypasses. The task applies
    // debugOutput only when it changes after "ready" (a value set at mount is lost).
    const [debugOutput, setDebugOutput] = createSignal(false);
    let adsState: AdsState = "none";
    let ads = 0;
    let media = "none";
    const report = (outcome: string) =>
        props.report([
            ["outcome", outcome],
            ["ads", ads],
            ["impressions", "na"],
            ["completes", "na"],
            ["errors", "na"],
            ["media", media]
        ]);
    // RAF never reaching "ready" is how a failed init looks: a stall still yields a line.
    const timeout = setTimeout(() => report(`timeout_${adsState}`), AD_TIMEOUT_MS);
    onCleanup(() => {
        clearTimeout(timeout);
        setCommand("stop");
    });
    return (
        <group>
            <rectangle ref={adView} width={1920} height={1080} color="0x00000000" />
            <Ads
                adUrl={prefixedUrl(props.proxyBase, props.separator, AD_TAG)}
                adView={adView}
                debugOutput={debugOutput()}
                onAdsState={state => {
                    adsState = state;
                    if (state !== "ready") return;
                    setDebugOutput(true);
                    setCommand("getAds");
                }}
                onGetAdsResult={(pods: AdPod[]) => {
                    ads = pods.reduce((n, pod) => n + (pod.ads?.length ?? 0), 0);
                    if (ads === 0) return report("no_ads");
                    const first = firstStreamUrl(pods);
                    if (first) media = isPrefixed(props.proxyBase, props.separator, first) ? "lab" : "direct";
                    setCommand("showAds");
                }}
                onShowAdsResult={result => {
                    if (result === "none") return; // cleared before the break runs
                    report(result === "user_exited" ? "exited" : result);
                }}
                command={command()} // last: the task reads the other fields when the command lands
            />
        </group>
    );
};

// The creative RAF will play first.
const firstStreamUrl = (pods: AdPod[]): string | undefined =>
    pods.flatMap(pod => pod.ads ?? []).find(ad => ad.streams?.length)?.streams?.[0]?.url;

export type LabCase = { label: string; component: Component<CaseProps> };

// The cases (traffic classes) by launch-param name, in menu order: the classic app's ids,
// labels and Origins. To add one: a component plus an entry here.
export const CASES: Record<string, LabCase> = {
    json_get: { label: "JSON GET", component: JsonGet },
    redirect: { label: "Redirect", component: Redirect },
    hls: { label: "HLS", component: Hls },
    dash: { label: "DASH", component: Dash },
    widevine: { label: "Widevine DASH", component: Widevine },
    json_post: { label: "JSON POST", component: JsonPost },
    image: { label: "Image (from catalog JSON)", component: Image },
    raf: { label: "RAF ad", component: Raf }
};
