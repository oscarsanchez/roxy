import type { AnchorNodeDescriptor, AnchorNodeImplementation } from "@roku-sdk/rsg-ts";
import { defineAnchorNode } from "@roku-sdk/rsg-ts";
import { createEffect, createSignal, untrack } from "@roku-sdk/solid";

import { prefixedUrl, useProxyBase, withRoxyAgent } from "../roxy-kit";

const ORIGIN_URL = "https://httpbin.org/json";

const ExampleAppDescriptor: AnchorNodeDescriptor = {
    componentName: "ExampleApp",
    extends: "Group" as const,
    inputFields: {},
    outputFields: {}
};

// One JSON request, through the kit. The result shows on screen and on the debug console.
const ExampleApp: AnchorNodeImplementation<typeof ExampleAppDescriptor> = () => {
    // The kit's wiring, step 1 of 2: read the proxyBase launch param in the root component.
    const proxyBase = useProxyBase();
    const [url, setUrl] = createSignal("");
    const [result, setResult] = createSignal("");

    // Step 2: once the launch params are in, every request goes to prefixedUrl(...) and its
    // Request gets withRoxyAgent(...). A Video's content node would take roxyCertificatesFile.
    createEffect(() => {
        const base = proxyBase();
        if (base === undefined || untrack(url)) return; // one request per launch
        const requestUrl = prefixedUrl(base, ORIGIN_URL);
        setUrl(requestUrl);
        fetch(new Request(requestUrl, withRoxyAgent())).then(
            async res => report(`status=${res.status} length=${(await res.text()).length}`),
            () => report("status=fetch_error")
        );
    });

    const report = (line: string) => {
        console.log(`ROXYKIT ${line}`);
        setResult(line);
    };

    return (
        <group>
            <rectangle width={1920} height={1080} color="0x101820FF" />
            <label translation={[120, 75]} text="roxy kit example (RSG 2.0)" />
            <label translation={[120, 180]} width={1680} wrap={true} text={url() ? `GET ${url()}` : ""} />
            <label translation={[120, 360]} width={1680} wrap={true} text={result()} />
        </group>
    );
};

export default defineAnchorNode(ExampleAppDescriptor, ExampleApp);
