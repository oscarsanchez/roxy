import { RokuConfig } from "@roku-sdk/rsg-ts/roku-config";

import { roxyBuildVariables, roxyPostBuild } from "./roxy-config";

const configuration: RokuConfig = {
    app: {
        entryPoint: "src/index.ts",
        buildVariables: { ...roxyBuildVariables },
        manifestEntries: {
            title: "roxy kit example (RSG 2.0)",
            major_version: 1,
            minor_version: 0,
            build_version: 1,
            ui_resolutions: "fhd",
            rsg_version: "2.0"
        }
    },
    pipeline: {
        build: {
            postBuild: roxyPostBuild
        }
    }
};

export default configuration;
