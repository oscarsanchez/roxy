import type { DomNode } from "@roku-sdk/interfaces";
import type { AnchorNodeDescriptor, AnchorNodeImplementation } from "@roku-sdk/rsg-ts";
import { defineAnchorNode } from "@roku-sdk/rsg-ts";
import { useLaunchConfig } from "@roku-sdk/runtime/launch-config";
import { createEffect, createSignal, Dynamic, onMount, Show, untrack } from "@roku-sdk/solid";

import { labCertificatesFile } from "../ca-routing";
import { type Report, resultLine } from "../result";
import { CASES } from "./cases";

// Launch params (ECP): proxyBase, separator, case, run. Without proxyBase, the build-time
// default is used. separator=/; builds Charles-style Prefixed URLs; anything else, the lab's own "/".
type LaunchParams = { proxyBase?: string; separator?: string; case?: string; run?: string };
type Run = { caseId: string; runId: string; proxyBase: string; separator: string; report: Report };

const CASE_IDS = Object.keys(CASES);

const LabAppDescriptor: AnchorNodeDescriptor = {
    componentName: "LabApp",
    extends: "Group" as const,
    inputFields: {},
    outputFields: {}
};

const LabApp: AnchorNodeImplementation<typeof LabAppDescriptor> = () => {
    const { launchParams } = useLaunchConfig<LaunchParams>();
    const proxyBase = () => launchParams().proxyBase || __DEFAULT_PROXY_BASE__;
    const separator = () => (launchParams().separator === "/;" ? "/;" : "/");
    const [run, setRun] = createSignal<Run>();
    const [result, setResult] = createSignal("");
    // The menu (a native LabelList) holds real focus; no focus framework is needed.
    let menu!: DomNode;
    onMount(() => menu.focus?.());

    // One result line per run, printed to the debug console and shown on screen.
    const reporter = (caseId: string, runId: string): Report => {
        let reported = false;
        return fields => {
            if (reported) return;
            reported = true;
            const line = resultLine(caseId, runId, fields);
            console.log(line);
            setResult(line);
            menu.focus?.(); // RAF takes focus for the break and never gives it back
        };
    };

    // A new Run object remounts the case, so picking the same menu item again reruns it.
    const startRun = (caseId: string, runId: string) => {
        const report = reporter(caseId, runId);
        if (!CASES[caseId]) {
            report([["status", "unknown_case"]]);
            return;
        }
        setRun({ caseId, runId, proxyBase: proxyBase(), separator: separator(), report });
    };

    // The first value is always {} (params arrive later), so act only once a case is named.
    createEffect(() => {
        const params = launchParams();
        if (!params.case) return;
        untrack(() => {
            const current = run();
            if (current && current.caseId === params.case && current.runId === (params.run ?? "")) return;
            startRun(params.case!, params.run ?? "");
        });
    });

    // Built once: the list's content never changes.
    const menuContent = (
        <contentNode>
            {CASE_IDS.map(id => (
                <contentNode title={CASES[id].label} />
            ))}
        </contentNode>
    );

    return (
        <group>
            <rectangle width={1920} height={1080} color="0x101820FF" />
            <label translation={[120, 75]} text="roxy Lab App (RSG 2.0)" />
            <label translation={[120, 150]} width={1680} text={labCertificatesFile ? "CA Routing build: Origin URLs" : `Proxy Base: ${proxyBase()}, separator ${separator()}`}
            />
            <label translation={[120, 225]} width={900} text={run() ? `Case: ${run()!.caseId}` : "No case"} />
            <labelList
                ref={menu}
                translation={[120, 300]}
                itemSize={[800, 66]}
                content={menuContent}
                // Same run id as the launch, as the classic menu does.
                onItemSelected={(index: number) => startRun(CASE_IDS[index], untrack(launchParams).run ?? "")}
            />
            <label translation={[120, 900]} width={1680} wrap={true} text={result()} />
            <Show when={run()} keyed>
                {r => <Dynamic component={CASES[r.caseId].component} proxyBase={r.proxyBase} separator={r.separator} report={r.report} />}
            </Show>
        </group>
    );
};

export default defineAnchorNode(LabAppDescriptor, LabApp);
