// roxy kit, build side, for RSG 2.0 apps. Copy it next to roku-config.ts, then in that file:
//   buildVariables: { ...roxyBuildVariables }   and   pipeline.build.postBuild: roxyPostBuild
// (call roxyPostBuild from your own postBuild if you have one). Guide: docs/prefix-routing.md.
//
// ROXY_KIT=1 in the build's environment sets the kit's build-time constant. Without it
// src/roxy-kit.ts compiles to no-ops and the package carries no proxy code: a release
// build never sets it.
// ROXY_CA_BUNDLE, with the kit only: a certificate bundle (public roots plus the lab's CA)
// for CA Routing. It ships at a pkg:/ path, since an HttpsAgent reads only pkg:/ files.
import { copyFile, mkdir } from "node:fs/promises";
import { dirname, join } from "node:path";

declare const process: { env: Record<string, string | undefined> };

const kit = process.env.ROXY_KIT === "1";
const caBundle = kit ? process.env.ROXY_CA_BUNDLE : undefined;
const CA_BUNDLE_PATH = "certs/lab-ca-bundle.crt";

export const roxyBuildVariables = {
    __ROXY_KIT__: kit,
    __ROXY_CA_BUNDLE__: caBundle ? `pkg:/${CA_BUNDLE_PATH}` : ""
};

// Before the package is archived: the bundle lands in the build output only.
export async function roxyPostBuild({ pkgDir }: { pkgDir: string }): Promise<void> {
    if (!caBundle) return;
    const target = join(pkgDir, CA_BUNDLE_PATH);
    await mkdir(dirname(target), { recursive: true });
    await copyFile(caBundle, target);
}
