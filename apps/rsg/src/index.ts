import "./compiled-components/BaseAppScene.xml";

import { enableExceptionTagging, main, registerAnchorNode } from "@roku-sdk/rsg-ts";

import LabApp from "./components/lab-app";

main(() => {
    enableExceptionTagging();
    registerAnchorNode(LabApp);
});
