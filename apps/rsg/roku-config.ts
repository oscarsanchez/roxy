import { copyFile, mkdir } from "node:fs/promises";
import { dirname, join } from "node:path";

import { RokuConfig } from "@roku-sdk/rsg-ts/roku-config";

declare const process: { env: Record<string, string | undefined> };

// scripts/deploy sets LAB_PROXY_BASE to the LAN Proxy Base: the build-time default
// used when the app is launched without a proxyBase launch param.
const defaultProxyBase = process.env.LAB_PROXY_BASE;
if (!defaultProxyBase) {
    throw new Error("LAB_PROXY_BASE is not set (build with scripts/deploy, or export it)");
}
// scripts/deploy --ca-routing sets ROXY_CA_BUNDLE (the variable the kit's example reads too)
// to a combined certificate bundle (public roots plus the lab's CA) generated outside the
// source tree. It ships in the package only, at this pkg:/ path: an HttpsAgent
// certificatesFile must be a pkg:/ file.
const caBundle = process.env.ROXY_CA_BUNDLE;
const CA_BUNDLE_PATH = "certs/lab-ca-bundle.crt";

const configuration: RokuConfig = {
    app: {
        entryPoint: "src/index.ts",
        buildVariables: {
            __DEFAULT_PROXY_BASE__: defaultProxyBase,
            __LAB_CA_BUNDLE__: caBundle ? `pkg:/${CA_BUNDLE_PATH}` : ""
        },
        images: {
            convertToWebp: true,
            generateHd: true
        },
        manifestEntries: {
            title: "roxy Lab App (RSG 2.0)",
            major_version: 1,
            minor_version: 0,
            build_version: 1,
            ui_resolutions: "fhd",
            uri_resolution_autosub: "*,sd,hd,fhd",
            mm_icon_focus_hd: "pkg:/images/app-icon-hd.png",
            mm_icon_focus_fhd: "pkg:/images/app-icon-fhd.png",
            splash_screen_hd: "pkg:/images/splash_hd.jpg",
            splash_color: "0x000000FF",
            splash_min_time: 1,
            rsg_version: "2.0",
            bs_libs_required: "roku_ads_lib", // RAF, for the raf case (@roku-sdk/ads)
            requires_widevine_drm: 1,
            requires_widevine_version: "1.0"
        }
    },
    pipeline: {
        build: {
            // Before the package is archived: the bundle lands in the build output only.
            postBuild: async ({ pkgDir }) => {
                if (!caBundle) return;
                const target = join(pkgDir, CA_BUNDLE_PATH);
                await mkdir(dirname(target), { recursive: true });
                await copyFile(caBundle, target);
            }
        }
    }
};

export default configuration;
